"""core.cli — CLI unificada `obsidian-master` (Story S06, Wave 6).

Cinco subcomandos stdlib-only (argparse):

- `init-db`    — cria/atualiza schema SQLite + marker de auto-discovery
- `scan`       — scan incremental (flag --no-embed pula embedder)
- `rebuild-db` — apaga DB e recria (confirma interativamente; --yes pula)
- `status`     — resumo do vault (notas ativas/deletadas, ultimo scan, DB size)
- `version`    — kit version + schema_version

Discovery do vault:
- Se `--vault PATH` passado: usa ele direto.
- Senao: walk ancestrais do cwd procurando `.obsidian-master/marker.json`.
- Sem marker e sem --vault: erro claro pedindo pra rodar dentro de vault
  ou passar --vault.

Exit codes: 0 ok, 1 abort/erro esperado, 2 argparse (unexpected).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from core.config import DB_PATH_REL
from core.db import connect
from core.scanner import scan


# ---------- helpers ----------


def _pkg_ver() -> str:
    try:
        return _pkg_version("obsidian-master-kit")
    except PackageNotFoundError:
        return "0.1.0+dev"


def _resolve_vault(raw: str | None) -> pathlib.Path:
    """Resolve o vault para um Path absoluto.

    - `raw` dado: expande user + resolve, devolve direto (mesmo sem marker —
      permite `init-db --vault NEW_DIR` pra bootstrap).
    - `raw` None: walk ancestrais do cwd procurando `.obsidian-master/marker.json`.
      Retorna o ancestor com marker.
    - Sem marker em nenhum ancestor: sys.exit(1) com mensagem util em pt-br.
    """
    if raw:
        return pathlib.Path(raw).expanduser().resolve()
    cur = pathlib.Path.cwd().resolve()
    while True:
        if (cur / ".obsidian-master" / "marker.json").exists():
            return cur
        if cur == cur.parent:
            break
        cur = cur.parent
    sys.exit(
        "Erro: nao encontrei vault obsidian-master em ancestrais de "
        f"{pathlib.Path.cwd()}. Rode dentro de um vault ou passe "
        "--vault PATH. Pra inicializar do zero, use "
        "'obsidian-master init-db --vault PATH'."
    )


def _ensure_marker(vault: pathlib.Path) -> None:
    """Garante `<vault>/.obsidian-master/marker.json` existe.

    Chamado por init-db e rebuild-db. Idempotente: se marker ja existe, no-op.
    Marker permite auto-discovery em chamadas subsequentes (cmd sem --vault).
    """
    marker = vault / ".obsidian-master" / "marker.json"
    if marker.exists():
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kit_version": _pkg_ver(),
        "initialized_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _schema_version(conn) -> int | None:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else None


# ---------- subcommands ----------


def cmd_init_db(args) -> int:
    # init-db tolera vault sem marker (esse e justamente o comando que cria)
    vault = (
        pathlib.Path(args.vault).expanduser().resolve()
        if args.vault
        else pathlib.Path.cwd().resolve()
    )
    conn = connect(vault)
    _ensure_marker(vault)
    ver = _schema_version(conn)
    vec = "ativo" if getattr(conn, "vec_loaded", False) else "fallback (sem sqlite-vec)"
    print(f"OK. Vault: {vault}")
    print(f"  DB:         {vault / DB_PATH_REL}")
    print(f"  Schema:     v{ver}")
    print(f"  Vec index:  {vec}")
    return 0


def cmd_scan(args) -> int:
    vault = _resolve_vault(args.vault)
    conn = connect(vault)
    embedder = None
    if not args.no_embed:
        try:
            from core.embeddings import get_default_embedder

            embedder = get_default_embedder()
        except Exception as exc:  # pragma: no cover — depende do ambiente
            print(
                f"Aviso: embedder indisponivel ({type(exc).__name__}: {exc}). "
                "Rodando sem re-embed.",
                file=sys.stderr,
            )
    t0 = time.perf_counter()
    report = scan(conn, vault, embedder=embedder)
    dt = time.perf_counter() - t0
    counts = report.counts
    print(f"Scan OK em {dt:.2f}s")
    print(f"  criadas:     {counts.get('created', 0)}")
    print(f"  atualizadas: {counts.get('updated', 0)}")
    print(f"  deletadas:   {counts.get('deleted', 0)}")
    print(f"  ignoradas:   {counts.get('skipped', 0)}")
    return 0


def cmd_rebuild_db(args) -> int:
    vault = _resolve_vault(args.vault)
    db_path = vault / DB_PATH_REL
    if db_path.exists() and not args.yes:
        resp = input(f"Isso vai APAGAR {db_path}. Continuar? [y/N]: ")
        if resp.strip().lower() not in ("y", "yes", "s", "sim"):
            print("Abortado.")
            return 1
    if db_path.exists():
        db_path.unlink()
    # limpa WAL/SHM sobrantes
    for suffix in ("-wal", "-shm"):
        leftover = db_path.with_name(db_path.name + suffix)
        if leftover.exists():
            leftover.unlink()
    conn = connect(vault)
    _ensure_marker(vault)
    ver = _schema_version(conn)
    print(f"DB recriado em {db_path}. Schema v{ver}.")
    print("Rode 'obsidian-master scan' pra repopular.")
    return 0


def cmd_status(args) -> int:
    vault = _resolve_vault(args.vault)
    db_path = vault / DB_PATH_REL
    if not db_path.exists():
        print(
            f"Erro: DB nao existe em {db_path}. "
            "Rode 'obsidian-master init-db' primeiro.",
            file=sys.stderr,
        )
        return 1
    conn = connect(vault)
    n_active = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL"
    ).fetchone()[0]
    n_deleted = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE deleted_at IS NOT NULL"
    ).fetchone()[0]
    last_scan_row = conn.execute(
        "SELECT ts FROM events WHERE event_type='scan_run' ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    size_kb = db_path.stat().st_size / 1024
    ver = _schema_version(conn)
    vec = "ativo" if getattr(conn, "vec_loaded", False) else "fallback"
    print(f"Vault: {vault}")
    print(f"  Notas ativas:    {n_active}")
    print(f"  Notas deletadas: {n_deleted}")
    print(f"  Ultimo scan:     {last_scan_row[0] if last_scan_row else '(nunca)'}")
    print(f"  Tamanho DB:      {size_kb:.1f} KB")
    print(f"  Schema:          v{ver}")
    print(f"  sqlite-vec:      {vec}")
    return 0


def cmd_upgrade(args) -> int:
    """Delega pro script skills/obsidian-librarian/scripts/upgrade.py.

    Motivo: upgrade.py e stdlib-only e nao depende do package core
    (via importlib.util isolation). Chamar via subprocess preserva esse
    invariante (e evita arrastar deps pesadas de core/__init__.py pra
    dentro da CLI). Output do script (JSON) passa por stdout cru.
    """
    import subprocess

    # Caminho do script e estavel no repo: skills/obsidian-librarian/scripts/upgrade.py.
    # O pacote instala via pyproject como dados (nao como package importavel),
    # entao resolvemos via path relativo ao __file__ da CLI.
    script = (
        pathlib.Path(__file__).resolve().parents[1]
        / "skills" / "obsidian-librarian" / "scripts" / "upgrade.py"
    )
    if not script.exists():
        print(
            f"Erro: script upgrade.py nao encontrado em {script}. Reinstale o kit.",
            file=sys.stderr,
        )
        return 1
    cmd = [sys.executable, str(script)]
    if args.vault:
        cmd += ["--vault", str(pathlib.Path(args.vault).expanduser().resolve())]
    return subprocess.call(cmd)


def cmd_version(args) -> int:
    kit_ver = _pkg_ver()
    # schema_version exige DB; se nao acharmos vault, so imprime kit version.
    try:
        vault = _resolve_vault(None)
    except SystemExit:
        print(f"obsidian-master-kit {kit_ver} (nenhum vault encontrado — schema N/A)")
        return 0
    conn = connect(vault)
    ver = _schema_version(conn)
    print(f"obsidian-master-kit {kit_ver} (schema v{ver})")
    return 0


# ---------- parser ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="obsidian-master",
        description=(
            "CLI unificada do obsidian-master-kit. "
            "Todos os subcomandos aceitam --vault PATH. Sem a flag, procura "
            "um vault nos ancestrais do diretorio atual (marker "
            ".obsidian-master/marker.json). Rode 'init-db' primeiro pra "
            "bootstrap de um vault novo."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="SUBCOMANDO")

    p_init = sub.add_parser(
        "init-db",
        help="Cria/atualiza schema SQLite no vault (idempotente).",
        description=(
            "Cria ou atualiza o schema SQLite em <vault>/.obsidian-master/db.sqlite "
            "e grava marker.json para auto-discovery. Idempotente: rodar 2x nao "
            "quebra nada."
        ),
    )
    p_init.add_argument(
        "--vault",
        help="Raiz do vault (default: diretorio atual). Nao precisa ter marker.",
    )
    p_init.set_defaults(func=cmd_init_db)

    p_scan = sub.add_parser(
        "scan",
        help="Varre o vault e atualiza o DB incrementalmente.",
        description=(
            "Scan incremental com delta em 3 niveis (mtime > hash > reparse). "
            "Com embedder, regera embeddings em mudancas semanticas "
            "significativas (>15%% word count, titulo, modelo)."
        ),
    )
    p_scan.add_argument("--vault", help="Raiz do vault (default: auto-discovery)")
    p_scan.add_argument(
        "--no-embed",
        action="store_true",
        help="Nao gera embeddings (mais rapido; util em CI ou sem model2vec).",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_rb = sub.add_parser(
        "rebuild-db",
        help="APAGA o DB e recria do zero (confirma antes; use 'scan' pra repopular).",
        description=(
            "Deleta o arquivo DB (e WAL/SHM residuais) e recria o schema do "
            "zero. Por default pede confirmacao interativa. Use --yes em "
            "scripts. Depois rode 'obsidian-master scan'."
        ),
    )
    p_rb.add_argument("--vault", help="Raiz do vault (default: auto-discovery)")
    p_rb.add_argument(
        "--yes",
        action="store_true",
        help="Pula confirmacao interativa (CUIDADO: apaga o DB sem perguntar).",
    )
    p_rb.set_defaults(func=cmd_rebuild_db)

    p_st = sub.add_parser(
        "status",
        help="Mostra resumo do vault + DB (notas, ultimo scan, tamanho).",
        description=(
            "Imprime contagem de notas ativas/deletadas, timestamp do ultimo "
            "scan registrado em events, tamanho do DB e status do sqlite-vec."
        ),
    )
    p_st.add_argument("--vault", help="Raiz do vault (default: auto-discovery)")
    p_st.set_defaults(func=cmd_status)

    p_up = sub.add_parser(
        "upgrade",
        help="Upgrade de vault v0.1.1 pra v1.0 (cria DB, popula, bumpa marker).",
        description=(
            "Migra um vault instalado com kit v0.1.1 pra v1.0: cria o DB "
            "SQLite, roda scan completo, emite eventos iniciais e bumpa o "
            "marker.json. Preserva CLAUDE.md e conteudo de notas. "
            "Idempotente — rodar 2x nao duplica events."
        ),
    )
    p_up.add_argument("--vault", help="Raiz do vault (default: auto-discovery)")
    p_up.set_defaults(func=cmd_upgrade)

    p_ve = sub.add_parser(
        "version",
        help="Mostra versao do kit e do schema DB.",
        description=(
            "Imprime a versao do pacote instalado e, se achar um vault, a "
            "versao do schema SQLite."
        ),
    )
    p_ve.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
