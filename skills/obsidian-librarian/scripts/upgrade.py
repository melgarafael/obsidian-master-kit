#!/usr/bin/env python3
"""Upgrade an obsidian-master-kit vault from v0.1.1 to v1.0 (Story S04).

Entrypoint: `python upgrade.py --vault <path>` or via `obsidian-master upgrade`.

Detecta vaults v0.1.1 (tem `.obsidian-master/marker.json` mas nao tem
`db.sqlite`), cria o DB via `core.db.connect` (que roda `ensure_schema`), faz
um scan completo via `core.scanner.scan`, emite eventos iniciais (`scan_run`
com `triggered_by=init` + `note_created` por nota + `link_added` por edge),
e atualiza o `marker.json` com `kit_version=1.0` + `schema_version=1` +
`upgraded_at`.

Idempotencia: se o vault ja e v1.0 (ou o db.sqlite ja existe), roda
`ensure_schema` (no-op se ja aplicado), re-scaneia (scanner e idempotente —
upserts com body_hash), e NAO emite `scan_run` re-duplicado (rerun retorna
`upgraded: false` com `reason='already_v1'`). Isso evita inflar a tabela de
events a cada rerun — a invariante "N reruns = 1 scan_run inicial" fica
preservada.

Preserva CLAUDE.md byte-identico. Nunca toca em conteudo de notas .md.

Stdlib-only. Reusa core/ via o mesmo padrao importlib.util do update_index.py.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util as _ilu
import json
import pathlib
import sys
import types as _types

_CORE_DIR = pathlib.Path(__file__).resolve().parents[3] / "core"
MARKER_REL = pathlib.Path(".obsidian-master/marker.json")
DB_REL = pathlib.Path(".obsidian-master/db.sqlite")


# ---------- core module loader (duplicado de update_index.py) ----------
#
# Decisao de reuso: DUPLICAR em vez de fatorar `_load_core_module` num
# shared module. Justificativa: update_index.py e um script standalone
# (shebang + `if __name__ == '__main__'`), extrair esse helper pra um
# `_lib.py` exigiria tocar o wave 2 codepath de events emission (que ja
# passou QA) apenas pra economizar ~30 linhas duplicadas. Trade-off:
# mid-epic refactor risk > codigo duplicado pequeno. Se wave 5+ precisar
# de um terceiro consumidor, fatoramos entao.


def _load_core_module(mod_name: str, filename: str):
    """Carrega core/<filename>.py e registra como `core.<mod_name>` em sys.modules.

    Evita executar `core/__init__.py` (que puxa networkx/model2vec como deps
    pesadas). Idempotente.
    """
    qualified = f"core.{mod_name}"
    if qualified in sys.modules:
        return sys.modules[qualified]

    if "core" not in sys.modules:
        _pkg = _types.ModuleType("core")
        _pkg.__path__ = [str(_CORE_DIR)]  # type: ignore[attr-defined]
        sys.modules["core"] = _pkg

    path = _CORE_DIR / filename
    spec = _ilu.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"core/{filename} nao encontrado em {path}")
    module = _ilu.module_from_spec(spec)
    sys.modules[qualified] = module
    sys.modules[f"_obm_core_{mod_name}"] = module
    spec.loader.exec_module(module)
    setattr(sys.modules["core"], mod_name, module)
    return module


# ---------- vault discovery (mesma logica do update_index.py) ----------


def find_vault_root(start: pathlib.Path) -> pathlib.Path:
    start = start.resolve()
    cur = start if start.is_dir() else start.parent
    while True:
        if (cur / MARKER_REL).exists():
            return cur
        if cur.parent == cur:
            raise SystemExit(
                f"Nenhum vault obsidian-master encontrado em {start} ou ancestrais. "
                "Passe --vault PATH ou rode dentro de um vault inicializado."
            )
        cur = cur.parent


# ---------- marker parsing ----------


def _parse_kit_version(raw: object) -> tuple[int, int, int] | None:
    """Converte `kit_version` string pra tupla comparavel. None se invalido.

    Aceita '0.1.0', '0.1.1', '1.0', '1.0.0' etc. Pad com zeros pra 3-tupla.
    """
    if not isinstance(raw, str):
        return None
    parts = raw.strip().split(".")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def _is_already_v1(marker_data: dict, db_exists: bool) -> bool:
    """Retorna True se o vault ja esta em v1.0 (ou acima).

    Criterio: db.sqlite existe E marker.kit_version >= (1, 0, 0). Ambos
    precisam bater — marker sem DB (corrompido) ainda e tratado como
    v0.1.1 pra re-criar o DB; DB sem marker bump (interrompido) e tratado
    como ja-v1 pra bumpar so o marker.
    """
    ver = _parse_kit_version(marker_data.get("kit_version"))
    if ver is None:
        return False
    if ver < (1, 0, 0):
        return False
    return db_exists


# ---------- events (duplicado minimalista de update_index.py) ----------
#
# So precisamos de INSERTs simples — nao usamos o dedup window do wave 2
# (scan_run init e uma vez so por vault, emitido em contexto controlado).
# Se o upgrade rodar 2x, o path idempotente nem chega aqui.


def _insert_event(
    conn,
    *,
    event_type: str,
    note_id: int | None = None,
    area_id: int | None = None,
    word_delta: int | None = None,
    metadata: dict | None = None,
) -> None:
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    ts = now.isoformat()
    date = ts[:10]
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    conn.execute(
        "INSERT INTO events (note_id, area_id, event_type, ts, date, word_delta, "
        "metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (note_id, area_id, event_type, ts, date, word_delta, meta_json),
    )


def _note_area_id(conn, note_id: int) -> int | None:
    row = conn.execute(
        "SELECT area_id FROM notes WHERE id=?", (note_id,)
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _emit_initial_events(conn, scan_report) -> dict[str, int]:
    """Emite scan_run(init) + note_created por nova nota + link_added por edge.

    Invariante: este helper so e chamado no path de upgrade-de-v0.1.1
    (DB recem criado, pre-scan zero notas/links). Entao:
    - scan_report.changes contem so 'created' (nenhuma 'updated'/'deleted'/'skipped')
    - links table esta 100% cheia de edges novos pos-scan

    Retorna Counter com totals por event_type.
    """
    counts = {"scan_run": 0, "note_created": 0, "link_added": 0}

    _insert_event(
        conn, event_type="scan_run", metadata={"triggered_by": "init"},
    )
    counts["scan_run"] += 1

    for change in scan_report.changes:
        if change.kind != "created" or change.note_id is None:
            # Paranoia: num DB limpo scanner so deveria emitir 'created'.
            # Se algo diferente aparecer (skipped por body_hash match apos
            # bug?), pulamos em vez de poluir events.
            continue
        area_id = _note_area_id(conn, change.note_id)
        _insert_event(
            conn, event_type="note_created", note_id=change.note_id,
            area_id=area_id, word_delta=change.word_delta,
        )
        counts["note_created"] += 1

    # Todos os links atuais sao "added" (pre-scan a tabela estava vazia).
    link_rows = conn.execute(
        "SELECT from_note_id, to_target FROM links"
    ).fetchall()
    for from_note_id, to_target in link_rows:
        area_id = _note_area_id(conn, int(from_note_id))
        _insert_event(
            conn, event_type="link_added", note_id=int(from_note_id),
            area_id=area_id,
            metadata={"to_target": to_target},
        )
        counts["link_added"] += 1

    conn.commit()
    return counts


# ---------- marker writer ----------


def _write_marker(marker_path: pathlib.Path, old_data: dict, now_iso: str) -> dict:
    """Atualiza marker.json preservando campos antigos.

    Adiciona/sobrescreve APENAS: kit_version, schema_version, upgraded_at.
    Todos os outros campos (created_at, initialized_at, note, etc.) sao
    preservados byte-identicos.
    """
    new_data = dict(old_data)  # shallow copy — marker e flat
    new_data["kit_version"] = "1.0"
    new_data["schema_version"] = 1
    new_data["upgraded_at"] = now_iso
    marker_path.write_text(
        json.dumps(new_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return new_data


# ---------- main ----------


def upgrade(vault: pathlib.Path) -> dict:
    """Executa o upgrade. Retorna dict com resumo (apropriado pra json.dumps).

    Fluxo:
    1. Le marker.json atual (precisa existir — e a ancora de discovery).
    2. Decide: ja-v1 (idempotent rerun) vs v0.1.1 (full upgrade).
    3. Em ambos os casos: abre conn (cria DB se faltava), ensure_schema
       (no-op se ja aplicado), roda scan completo.
    4. Em v0.1.1: emite eventos iniciais, bumpa marker.
       Em ja-v1: nao emite scan_run duplicado, nao bumpa marker.
    """
    marker_path = vault / MARKER_REL
    db_path = vault / DB_REL

    if not marker_path.exists():
        raise SystemExit(
            f"marker.json nao encontrado em {marker_path}. Esse vault nao parece "
            "ter sido inicializado pelo obsidian-master-kit. Rode "
            "'obsidian-master init-db' primeiro."
        )

    marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
    db_was_present = db_path.exists()
    already_v1 = _is_already_v1(marker_data, db_was_present)

    now_iso = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()

    # Carrega core.db e core.scanner tardiamente pra nao pagar import cost
    # se o argparse falhar. connect() cria o arquivo .sqlite + roda
    # ensure_schema automaticamente.
    core_db = _load_core_module("db", "db.py")
    core_scanner = _load_core_module("scanner", "scanner.py")

    conn = core_db.connect(vault)
    try:
        # Scan sempre — idempotente por design (body_hash gate).
        scan_report = core_scanner.scan(conn, vault)

        if already_v1:
            # Rerun: ensure_schema ja foi no connect, scan rodou. Nao
            # emitimos scan_run pra nao duplicar o evento inicial. Nao
            # bumpamos marker (ja e >=1.0). Idempotencia bit-preserving.
            result = {
                "upgraded": False,
                "reason": "already_v1",
                "notes_scanned": len(scan_report.changes),
                "scan_counts": scan_report.counts,
                "events_emitted": {},
                "marker_changed": False,
                "kit_version_before": marker_data.get("kit_version"),
                "kit_version_after": marker_data.get("kit_version"),
            }
        else:
            # Upgrade de fato: emite events iniciais + bumpa marker.
            events_counts = _emit_initial_events(conn, scan_report)
            new_marker = _write_marker(marker_path, marker_data, now_iso)
            result = {
                "upgraded": True,
                "reason": (
                    "db_missing" if not db_was_present else "kit_version_below_1"
                ),
                "notes_scanned": len(scan_report.changes),
                "scan_counts": scan_report.counts,
                "events_emitted": events_counts,
                "marker_changed": True,
                "kit_version_before": marker_data.get("kit_version"),
                "kit_version_after": new_marker["kit_version"],
                "upgraded_at": now_iso,
            }
    finally:
        conn.close()

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Upgrade um vault obsidian-master-kit de v0.1.1 pra v1.0: cria o DB "
            "SQLite, popula via scan completo, emite eventos iniciais, e bumpa "
            "o marker. Idempotente — rodar 2x nao duplica dados."
        ),
    )
    parser.add_argument(
        "--vault",
        default=".",
        help="Raiz do vault (default: auto-discovery via walk-up do cwd).",
    )
    args = parser.parse_args(argv)

    start = pathlib.Path(args.vault).expanduser().resolve()
    vault = find_vault_root(start)

    try:
        result = upgrade(vault)
    except Exception as exc:
        err = {
            "upgraded": False,
            "reason": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
        sys.stdout.write(json.dumps(err, indent=2, ensure_ascii=False) + "\n")
        return 1

    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
