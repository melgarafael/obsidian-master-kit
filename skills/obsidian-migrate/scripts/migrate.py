#!/usr/bin/env python3
"""CLI do skill obsidian-migrate. Opcao C (hibrida) pra adocao do kit
em vault existente. Wave 1 implementa 'status'; Wave 2 adiciona
'shadow-scan'; demais comandos sao stubs declarados (Waves 3-6 flesham).
"""
from __future__ import annotations
import argparse
import datetime as _dt
import json
import pathlib
import shutil
import sys
import time


VALID_STATES = ("empty", "existing", "already_migrated")


def detect_state(vault: pathlib.Path) -> str:
    """Detecta o estado do vault pra fins de migracao.

    - empty: diretorio nao existe OU existe mas nao tem nenhum .md fora de
      pastas ignoradas
    - already_migrated: tem .obsidian-master/marker.json
    - existing: tem .md e nao tem marker
    """
    if not vault.exists() or not vault.is_dir():
        return "empty"
    marker = vault / ".obsidian-master" / "marker.json"
    if marker.exists():
        return "already_migrated"
    # Procura qualquer .md fora de ignored
    ignore = {".obsidian", ".trash", ".obsidian-master", ".git", "node_modules",
              "_templates"}
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault)
        if any(part in ignore or part.startswith(".") for part in rel.parts[:-1]):
            continue
        return "existing"
    return "empty"


def cmd_status(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    state = detect_state(vault)
    print(f"Estado do vault: {state}")
    print(f"Caminho: {vault}")
    if state == "already_migrated":
        marker = vault / ".obsidian-master" / "marker.json"
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            mig = data.get("migration_completed", False)
            print(f"  marker.json: kit_version={data.get('kit_version', '?')}, "
                  f"migration_completed={mig}")
        except Exception as e:
            print(f"  marker.json: presente, mas falhou parse ({e})")
        print("Erro: vault ja tem marker obsidian-master. Pra sincronizar, "
              "use obsidian-librarian. Pra reconstruir do zero, remova "
              ".obsidian-master/ e rode obsidian-init.", file=sys.stderr)
        return 1
    elif state == "empty":
        print("Vault vazio (ou sem .md fora de pastas ignoradas).")
        print("Sugestao: use obsidian-init pra scaffold de um vault do zero.")
        return 0
    else:  # existing
        print("Vault existente sem marker. Pronto pra migracao.")
        print("Proximo passo: migrate.py shadow-scan --vault PATH (Wave 2)")
        return 0


# ---------------------------------------------------------------------------
# Wave 2: shadow-scan
# ---------------------------------------------------------------------------
def _vault_size_bytes(vault: pathlib.Path) -> int:
    """Soma tamanho de todos os arquivos no vault (best-effort). Ignora
    arquivos que derem OSError no stat (symlinks quebrados, permission
    denied) — nao abortamos por causa deles."""
    total = 0
    for p in vault.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _find_recent_backup(
    vault: pathlib.Path, within_hours: int = 24
) -> pathlib.Path | None:
    """Retorna um backup `<vault>.backup-*` com mtime <= within_hours,
    se existir. Usa mtime (nao parse do nome) pra robustez a timezone/
    clock skew."""
    parent = vault.parent
    now = time.time()
    for candidate in parent.glob(f"{vault.name}.backup-*"):
        if not candidate.is_dir():
            continue
        try:
            age_h = (now - candidate.stat().st_mtime) / 3600
        except OSError:
            continue
        if age_h <= within_hours:
            return candidate
    return None


def _make_backup(vault: pathlib.Path) -> pathlib.Path:
    """Cria backup com timestamp. Usa shutil.copytree com copy2 pra
    preservar permissoes e metadados."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    dest = vault.parent / f"{vault.name}.backup-{timestamp}"
    shutil.copytree(vault, dest, symlinks=False, copy_function=shutil.copy2)
    return dest


def cmd_shadow_scan(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    if not vault.exists() or not vault.is_dir():
        print(f"Erro: vault {vault} nao existe.", file=sys.stderr)
        return 1
    if (vault / ".obsidian-master" / "marker.json").exists():
        print("Erro: vault ja migrado (tem marker.json). Abortando.",
              file=sys.stderr)
        return 1

    # --- Disk check: precisa 2x o tamanho do vault livre no parent ---
    vault_size = _vault_size_bytes(vault)
    free = shutil.disk_usage(vault.parent).free
    if free < 2 * vault_size:
        print(f"Erro: espaco livre insuficiente. Precisa 2x do vault "
              f"({2*vault_size/1e6:.1f} MB), disponivel {free/1e6:.1f} MB. "
              f"Abortando.", file=sys.stderr)
        return 1

    # --- Backup (skip se houver recente, a menos que --force-backup) ---
    recent = _find_recent_backup(vault, within_hours=24)
    if recent is not None and not args.force:
        backup_path = recent
        print(f"Backup recente encontrado em {backup_path} "
              f"(<24h). Reutilizando. Use --force-backup pra sobrescrever.")
    else:
        backup_path = _make_backup(vault)
        print(f"Backup criado em {backup_path}")

    # --- Scan via core (lazy import: status nao paga o custo) ---
    from core.db import connect
    from core.scanner import scan

    conn = connect(vault)

    embedder = None
    if not args.no_embed:
        try:
            from core.embeddings import get_default_embedder
            embedder = get_default_embedder()
        except Exception as e:
            print(f"Aviso: embedder indisponivel ({e}). Scan sem re-embed.",
                  file=sys.stderr)

    report = scan(conn, vault, embedder=embedder)

    # --- Emite event (migrate e responsavel, nao o scanner — amendment Epic 01) ---
    now = _dt.datetime.now().astimezone()
    conn.execute(
        "INSERT INTO events(event_type, ts, date, metadata_json) "
        "VALUES (?, ?, ?, ?)",
        (
            "scan_run",
            now.isoformat(timespec="seconds"),
            now.date().isoformat(),
            json.dumps({
                "mode": "shadow",
                "backup_path": str(backup_path),
                "counts": dict(report.counts),
            }),
        ),
    )
    conn.commit()

    # --- Relatorio ---
    db_path = vault / ".obsidian-master" / "db.sqlite"
    total = sum(report.counts.values())
    print(f"Shadow scan OK em {report.duration_s:.2f}s")
    print(f"  Backup: {backup_path}")
    print(f"  DB:     {db_path}")
    print(f"  Notas:  {total} total "
          f"(+{report.counts.get('created', 0)} criadas, "
          f"{report.counts.get('skipped', 0)} skipped)")
    folder_counts = conn.execute(
        """SELECT COALESCE(
                    NULLIF(SUBSTR(path, 1, INSTR(path || '/', '/') - 1), ''),
                    '(raiz)') AS folder,
                  COUNT(*) AS n
             FROM notes
            WHERE deleted_at IS NULL
         GROUP BY folder
         ORDER BY n DESC"""
    ).fetchall()
    if folder_counts:
        print("  Por pasta top-level:")
        for folder, n in folder_counts:
            label = folder if folder else "(raiz)"
            print(f"    {label:<30} {n}")
    try:
        size = db_path.stat().st_size
        print(f"  Tamanho DB: {size/1024:.1f} KB")
    except OSError:
        pass

    conn.close()
    return 0


def _stub(wave: int, cmd: str):
    """Gera um handler stub pra subcommand nao implementado ainda."""
    def handler(args) -> int:
        print(f"Subcommand '{cmd}' ainda nao implementado (planejado pra Wave {wave}).",
              file=sys.stderr)
        return 2
    return handler


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate.py",
        description=(
            "CLI do skill obsidian-migrate. Adota o kit em vault existente "
            "sem destruir estrutura (Opcao C hibrida). Fluxo: status -> "
            "shadow-scan -> cluster -> propose -> plan -> approve -> apply."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # Wave 1: status
    p_st = sub.add_parser("status", help="Detecta estado do vault (empty|existing|already_migrated)")
    p_st.add_argument("--vault", required=True, help="Raiz do vault a inspecionar")
    p_st.set_defaults(func=cmd_status)

    # Wave 2: shadow-scan
    p_ss = sub.add_parser(
        "shadow-scan", help="Backup + scan inicial sem mover arquivos"
    )
    p_ss.add_argument("--vault", required=True)
    p_ss.add_argument(
        "--no-embed", action="store_true",
        help="Pula embedder (mais rapido; util em CI)",
    )
    p_ss.add_argument(
        "--force-backup", action="store_true", dest="force",
        help="Cria backup mesmo se ja houver um recente (<24h)",
    )
    p_ss.set_defaults(func=cmd_shadow_scan)

    # Stubs pras proximas waves
    for (w, name, help_text) in [
        (3, "cluster",     "HDBSCAN sobre embeddings + labels de cluster"),
        (4, "propose",     "Gera migration-proposal.md + CLAUDE.md preview"),
        (5, "plan",        "Popula migration_plan em lotes de 20"),
        (5, "approve",     "Approval interativo por batch"),
        (6, "apply",       "Aplica renames do batch (Wave 6)"),
        (6, "rollback",    "Reverte renames do batch (Wave 6)"),
    ]:
        p_cmd = sub.add_parser(name, help=help_text)
        p_cmd.add_argument("--vault", required=True)
        p_cmd.set_defaults(func=_stub(w, name))

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
