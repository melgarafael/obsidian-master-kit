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


# ---------------------------------------------------------------------------
# Wave 3: cluster (HDBSCAN + TF-IDF labeling)
# ---------------------------------------------------------------------------
def cmd_cluster(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    db_path = vault / ".obsidian-master" / "db.sqlite"
    if not db_path.exists():
        print("Erro: DB nao existe. Rode 'shadow-scan' primeiro.", file=sys.stderr)
        return 1

    from core.db import connect
    conn = connect(vault)

    # Load notes with embeddings
    notes, embeddings = _load_notes_with_embeddings(conn)
    if len(notes) < 10:
        print(f"Erro: so {len(notes)} notas com embedding. Minimo recomendado: 10.",
              file=sys.stderr)
        return 1

    # Cluster
    import numpy as np
    n = len(notes)
    min_cluster_size = max(5, n // 200)
    labels = _run_hdbscan(embeddings, min_cluster_size=min_cluster_size, min_samples=3)

    # Per-cluster summarize
    cluster_summaries = _summarize_clusters(notes, embeddings, labels, top_k_tokens=8,
                                              top_k_central=3)

    # Optional AI labeling
    if args.ai_label:
        for cs in cluster_summaries:
            cs["label"] = _ai_label(cs) or cs["label"]

    # Persist
    run_id = _persist_clusters(conn, cluster_summaries, min_cluster_size=min_cluster_size)

    # Report
    print(f"HDBSCAN OK. run_id={run_id}")
    n_noise = int(np.sum(labels == -1))
    n_clusters = len([c for c in cluster_summaries if c["cluster_label_id"] != -1])
    print(f"  {n_clusters} clusters + {n_noise} noise (de {n} notas)")
    print(f"  min_cluster_size={min_cluster_size}, min_samples=3")
    for cs in cluster_summaries:
        print(f"  [{cs['cluster_label_id']:>3}] {cs['note_count']:>4} notas — {cs['label']}")
    return 0


def _load_notes_with_embeddings(conn):
    """Retorna (list[dict(id, path, title)], np.ndarray de shape (N, dim))."""
    import numpy as np
    notes = []
    embs = []
    vec_loaded = getattr(conn, "vec_loaded", False)
    if vec_loaded:
        rows = conn.execute("""
            SELECT n.id, n.path, n.title, vn.embedding
            FROM notes n
            JOIN vec_notes vn ON vn.note_id = n.id
            WHERE n.deleted_at IS NULL
        """).fetchall()
        for nid, path, title, emb_bytes in rows:
            notes.append({"id": nid, "path": path, "title": title})
            embs.append(np.frombuffer(emb_bytes, dtype=np.float32))
    else:
        rows = conn.execute("""
            SELECT n.id, n.path, n.title, neb.vec
            FROM notes n
            JOIN notes_embedding_blob neb ON neb.note_id = n.id
            WHERE n.deleted_at IS NULL
        """).fetchall()
        for nid, path, title, vec_bytes in rows:
            notes.append({"id": nid, "path": path, "title": title})
            embs.append(np.frombuffer(vec_bytes, dtype=np.float32))
    if not embs:
        return [], np.zeros((0, 0), dtype=np.float32)
    return notes, np.vstack(embs)


def _run_hdbscan(embeddings, *, min_cluster_size: int, min_samples: int):
    from sklearn.cluster import HDBSCAN
    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",  # equivalente a cosine em L2-normalized vectors (Epic 01)
        copy=True,  # future default (1.10); silencia FutureWarning
    )
    return model.fit_predict(embeddings)


def _summarize_clusters(notes, embeddings, labels, *, top_k_tokens: int, top_k_central: int):
    """Para cada cluster (!=-1), extrai top tokens TF-IDF + notas centrais + label."""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    summaries = []
    unique_labels = sorted({int(l) for l in labels if l != -1})
    if not unique_labels:
        return summaries

    titles = [n["title"] or "" for n in notes]
    stopwords = _stopwords_pt_br_en()
    vec = TfidfVectorizer(
        max_features=2000,
        ngram_range=(1, 2),
        lowercase=True,
        stop_words=list(stopwords),
        token_pattern=r"(?u)\b[a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ\-']{2,}\b",
    )
    try:
        tfidf = vec.fit_transform(titles)
        feature_names = vec.get_feature_names_out()
    except ValueError:
        tfidf = None
        feature_names = []

    for cl in unique_labels:
        idx = np.where(labels == cl)[0]
        cluster_embs = embeddings[idx]
        cluster_notes = [notes[i] for i in idx]
        centroid = cluster_embs.mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-9)
        dists = np.linalg.norm(cluster_embs - centroid, axis=1)
        central_order = np.argsort(dists)
        central = [cluster_notes[j] for j in central_order[:top_k_central]]
        central_distances = [float(dists[j]) for j in central_order[:top_k_central]]

        top_tokens = []
        if tfidf is not None and len(feature_names) > 0:
            cluster_tfidf = tfidf[idx].mean(axis=0)
            arr = np.asarray(cluster_tfidf).flatten()
            order = arr.argsort()[::-1]
            top_tokens = [str(feature_names[k]) for k in order[:top_k_tokens] if arr[k] > 0]

        label_parts = []
        if top_tokens:
            label_parts.append(" / ".join(top_tokens[:3]))
        if central:
            label_parts.append(f"(ex: {central[0]['title'][:40]})")
        label = " ".join(label_parts) or f"cluster-{cl}"

        summaries.append({
            "cluster_label_id": int(cl),
            "label": label,
            "label_source": "auto_tfidf",
            "note_count": len(idx),
            "note_ids": [int(n["id"]) for n in cluster_notes],
            "top_tokens": top_tokens,
            "central_note_ids": [int(n["id"]) for n in central],
            "central_distances": central_distances,
        })
    return summaries


def _persist_clusters(conn, summaries, *, min_cluster_size: int) -> str:
    run_id = _dt.datetime.now().strftime("hdbscan-%Y%m%d-%H%M%S")
    now = _dt.datetime.now().astimezone().isoformat(timespec="seconds")

    with conn:
        for cs in summaries:
            cur = conn.execute(
                """INSERT INTO clusters(run_id, label, label_source, algorithm,
                                         similarity_threshold, note_count, created_at)
                   VALUES (?, ?, ?, 'hdbscan', ?, ?, ?)""",
                (run_id, cs["label"], cs["label_source"],
                 float(min_cluster_size), cs["note_count"], now),
            )
            cluster_id = cur.lastrowid
            # Build distance list: central notes get real distances, others get None.
            central_ids = cs["central_note_ids"]
            central_dists = cs["central_distances"]
            central_map = {nid: d for nid, d in zip(central_ids, central_dists)}
            for nid in cs["note_ids"]:
                conn.execute(
                    "INSERT INTO cluster_notes(cluster_id, note_id, distance_to_centroid) "
                    "VALUES (?, ?, ?)",
                    (cluster_id, nid, central_map.get(nid)),
                )
    return run_id


def _stopwords_pt_br_en():
    """Lista curada de stopwords pt-br + en pra TF-IDF."""
    pt_br = {
        "a","à","ao","aos","aquela","aquelas","aquele","aqueles","aquilo","as","até",
        "com","como","da","das","de","dela","delas","dele","deles","depois","do","dos",
        "e","é","ela","elas","ele","eles","em","entre","era","eram","essa","essas",
        "esse","esses","esta","está","estamos","estão","estas","este","esteja","estejam",
        "estejamos","estes","esteve","estive","estivemos","estiver","estivera","estiveram",
        "estiverem","estivermos","estivesse","estivessem","estivéssemos","estou","eu",
        "foi","fomos","for","fora","foram","forem","formos","fosse","fossem","fôssemos",
        "fui","há","haja","hajam","hajamos","hão","havemos","haver","havia","houve",
        "houvemos","houver","houvera","houveram","houverão","houverei","houverem",
        "houveremos","houveria","houveriam","houveríamos","houvermos","houvesse",
        "houvessem","houvéssemos","isso","isto","já","lhe","lhes","mais","mas","me",
        "mesmo","meu","meus","minha","minhas","muito","na","não","nas","nem","no",
        "nos","nós","nossa","nossas","nosso","nossos","num","numa","o","os","ou",
        "para","pela","pelas","pelo","pelos","por","qual","quando","que","quem","são",
        "se","seja","sejam","sejamos","sem","ser","será","serão","serei","seremos",
        "seria","seriam","seríamos","seu","seus","só","somos","sou","sua","suas",
        "também","te","tem","tém","temos","tenha","tenham","tenhamos","tenho","ter",
        "terá","terão","terei","teremos","teria","teriam","teríamos","teu","teus",
        "teve","tinha","tinham","tínhamos","tive","tivemos","tiver","tivera","tiveram",
        "tiverem","tivermos","tivesse","tivessem","tivéssemos","tu","tua","tuas","um",
        "uma","você","vocês","vos",
    }
    en = {
        "a","an","the","and","or","but","if","is","are","was","were","be","been","being",
        "to","of","in","on","at","for","with","by","from","as","about","into","through",
        "it","its","i","you","he","she","we","they","this","that","these","those","there",
    }
    return pt_br | en


def _ai_label(cluster_summary: dict) -> str | None:
    """Invoca claude CLI com prompt curto pra gerar label. None se falhar."""
    import subprocess
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return None
    prompt = (
        "Gere um label curto (3-6 palavras, em pt-br) pra esse cluster de notas "
        "Obsidian. Responda SO o label, sem explicacao.\n\n"
        f"Top tokens TF-IDF: {', '.join(cluster_summary['top_tokens'][:8])}\n"
        f"Total de notas: {cluster_summary['note_count']}\n"
        f"Label heuristico atual: {cluster_summary['label']}\n"
    )
    try:
        r = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return r.stdout.strip().split("\n")[0][:100]
    except Exception:
        pass
    return None


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

    # Wave 3: cluster
    p_cl = sub.add_parser("cluster", help="HDBSCAN sobre embeddings + labels TF-IDF")
    p_cl.add_argument("--vault", required=True)
    p_cl.add_argument(
        "--ai-label", action="store_true",
        help="Invoca Claude CLI pra labels mais descritivos (opcional)",
    )
    p_cl.set_defaults(func=cmd_cluster)

    # Stubs pras proximas waves
    for (w, name, help_text) in [
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
