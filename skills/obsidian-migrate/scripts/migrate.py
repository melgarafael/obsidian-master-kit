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


# ---------------------------------------------------------------------------
# Wave 4: propose (folder -> area mapping + CLAUDE.md preview)
# ---------------------------------------------------------------------------
def _load_folder_cluster_distribution(conn, vault):
    """Retorna dict: folder -> {cluster_id -> count}, incluindo 'noise' (notas fora de cluster).

    Considera apenas top-level folders (primeiro segmento do path).
    Notas na raiz (sem folder) vao em '(raiz)'.
    """
    rows = conn.execute("""
        SELECT n.path,
               cn.cluster_id,
               c.label
        FROM notes n
        LEFT JOIN cluster_notes cn ON cn.note_id = n.id
        LEFT JOIN clusters c ON c.id = cn.cluster_id
        WHERE n.deleted_at IS NULL
    """).fetchall()

    from collections import defaultdict
    distribution = defaultdict(lambda: {"total": 0, "by_cluster": defaultdict(int),
                                         "by_label": {}})
    for path, cluster_id, cluster_label in rows:
        parts = path.split("/", 1)
        folder = parts[0] if len(parts) > 1 else "(raiz)"
        distribution[folder]["total"] += 1
        key = cluster_id if cluster_id is not None else "noise"
        distribution[folder]["by_cluster"][key] += 1
        if cluster_label and cluster_id is not None:
            distribution[folder]["by_label"][cluster_id] = cluster_label
    return dict(distribution)


def _propose_folder_areas(distribution, dominance_threshold: float = 0.60):
    """Pra cada folder, determina area proposta.

    Retorna list[dict] com: folder, total, dominant_cluster_id, dominant_label,
      dominance, area_slug (proposta), status (clear|ambiguous|noise_heavy).
    """
    proposals = []
    for folder, data in sorted(distribution.items()):
        total = data["total"]
        by_cluster = data["by_cluster"]
        # Descarta noise pra calculo de dominancia entre clusters reais
        real = {k: v for k, v in by_cluster.items() if k != "noise"}
        noise_count = by_cluster.get("noise", 0)

        if not real:
            # Tudo noise
            proposals.append({
                "folder": folder, "total": total, "status": "noise_heavy",
                "dominant_cluster_id": None, "dominant_label": None,
                "dominance": 0.0, "area_slug": None, "area_label": None,
                "noise_count": noise_count,
            })
            continue

        dominant_id = max(real, key=real.get)
        dominant_count = real[dominant_id]
        dominance = dominant_count / total
        dominant_label = data["by_label"].get(dominant_id, f"cluster-{dominant_id}")

        status = "clear" if dominance >= dominance_threshold else "ambiguous"
        area_slug = _slug(folder) if status == "clear" else None
        area_label = folder if status == "clear" else None

        proposals.append({
            "folder": folder, "total": total,
            "dominant_cluster_id": int(dominant_id),
            "dominant_label": dominant_label,
            "dominance": round(dominance, 3),
            "status": status,
            "area_slug": area_slug,
            "area_label": area_label,
            "noise_count": noise_count,
        })
    return proposals


def _slug(folder: str) -> str:
    """'01 - Profissional' -> 'profissional', 'Research & Dev' -> 'research-dev'."""
    import re as _re
    s = folder.lower()
    # remove numero-hifen prefix
    s = _re.sub(r"^\d+\s*[-_]\s*", "", s)
    # normalize separators
    s = _re.sub(r"[&/\s]+", "-", s)
    s = _re.sub(r"[^a-z0-9\-]", "", s)
    s = _re.sub(r"-+", "-", s).strip("-")
    return s or "area"


def _write_proposal_md(vault, proposals, discovered_areas, claude_md_preview):
    """Escreve .obsidian-master/migration-proposal.md."""
    out_path = vault / ".obsidian-master" / "migration-proposal.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# Proposta de Migracao (Opcao C)")
    lines.append("")
    lines.append(
        "> Gerada por `obsidian-migrate propose`. **Voce pode editar este arquivo a mao** "
        "antes de rodar `migrate.py plan`. Alteracoes que importam: a coluna 'Area "
        "proposta' da tabela. Linhas em 'Pastas ambiguas' ficam vazias — decida voce."
    )
    lines.append("")

    lines.append("## Mapeamento pasta -> area")
    lines.append("")
    lines.append("| Pasta | Notas | Cluster dominante | Dominancia | Area proposta | Status |")
    lines.append("|---|---|---|---|---|---|")
    for p in proposals:
        if p["status"] == "clear":
            area = f"`{p['area_slug']}`"
        elif p["status"] == "ambiguous":
            area = "_(decidir)_"
        else:
            area = "_(ruido)_"
        dom_str = f"{p['dominance']*100:.0f}%" if p["status"] != "noise_heavy" else "-"
        label = (p["dominant_label"] or "-")[:50]
        lines.append(f"| {p['folder']} | {p['total']} | {label} | {dom_str} | {area} | {p['status']} |")
    lines.append("")

    ambiguous = [p for p in proposals if p["status"] == "ambiguous"]
    if ambiguous:
        lines.append("## Pastas ambiguas (sem cluster dominante >=60%)")
        lines.append("")
        for p in ambiguous:
            lines.append(f"- **{p['folder']}**: {p['total']} notas, dominante "
                         f"`{p['dominant_label']}` mas so {p['dominance']*100:.0f}%. "
                         "Edite a linha na tabela acima com uma area manualmente.")
        lines.append("")

    lines.append("## Areas canonicas (opcionais)")
    lines.append("")
    lines.append("O kit tem 4 areas canonicas que voce pode adicionar alem das descobertas:")
    lines.append("")
    lines.append("- `pessoal` — Pessoal / Journaling / Memorias")
    lines.append("- `profissional` — Profissional / Projetos / Clientes")
    lines.append("- `pesquisa` — Pesquisas e Estudos")
    lines.append("- `ai-memory` — Memoria da IA (contexto de sessoes)")
    lines.append("")
    lines.append("Se quiser usa-las, adicione a coluna 'Area proposta' das linhas relevantes.")
    lines.append("")

    lines.append("## Preview do CLAUDE.md")
    lines.append("")
    lines.append("Quando voce rodar `migrate.py apply` apos approval, este CLAUDE.md sera gerado")
    lines.append("na raiz do vault:")
    lines.append("")
    lines.append("```markdown")
    lines.append(claude_md_preview)
    lines.append("```")
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _render_claude_md(discovered_areas: list[dict]) -> str:
    """Renderiza CLAUDE.md adaptativo dado o set de areas descobertas."""
    lines = [
        "# CLAUDE.md — Doutrina deste vault",
        "",
        "> Este arquivo e a doutrina humana do vault. Edite livremente. O bibliotecario",
        "> (`obsidian-librarian`) le este arquivo pra entender o contexto e nao sobrescreve-lo.",
        "",
        "## Mapa de Areas",
        "",
        "Este vault tem as seguintes areas, descobertas via clustering automatico do seu conteudo:",
        "",
    ]
    for a in discovered_areas:
        lines.append(f"- **`{a['slug']}`** — {a['label']} ({a['note_count']} notas)")
    lines.append("")
    lines.append("## Convencoes de frontmatter")
    lines.append("")
    lines.append("Toda nota tem:")
    lines.append("- `created: YYYY-MM-DD` — data de criacao")
    lines.append("- `updated: YYYY-MM-DD` — ultima atualizacao")
    lines.append("- `area: <slug>` — uma das areas acima")
    lines.append("- `type: <nota|projeto|pesquisa|diario|referencia|moc>` — tipo da nota")
    lines.append("- `status: <draft|ativo|arquivado>` — ciclo de vida")
    lines.append("- `tags: [list, em, formato, pai/filho]` — tags hierarquicas")
    lines.append("")
    lines.append("## Regras de ouro")
    lines.append("")
    lines.append("- Nomes de pasta em pt-br exceto as 4 canonicas se voce adotar (pessoal, profissional, pesquisa, ai-memory)")
    lines.append("- Links usam wiki-links `[[Nota X]]` ou `[[Nota X|alias]]`")
    lines.append("- Cada area tem um `_MOC.md` no nivel top (Map of Content)")
    lines.append("")
    return "\n".join(lines)


def _persist_discovered_areas(conn, proposals):
    """Grava em `areas` as areas com status='clear'. Noop pras ambiguas/noise."""
    import datetime as _dt
    now = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    created = []
    with conn:
        for p in proposals:
            if p["status"] != "clear":
                continue
            # Idempotente: evita duplicar em re-runs
            existing = conn.execute(
                "SELECT id FROM areas WHERE slug=?", (p["area_slug"],)
            ).fetchone()
            if existing:
                continue
            conn.execute(
                """INSERT INTO areas(slug, label, folder, is_canonical, sensitive, created_at)
                   VALUES (?, ?, ?, 0, 0, ?)""",
                (p["area_slug"], p["area_label"], p["folder"], now),
            )
            created.append(p["area_slug"])
    return created


def cmd_propose(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    db_path = vault / ".obsidian-master" / "db.sqlite"
    if not db_path.exists():
        print("Erro: DB nao existe. Rode 'shadow-scan' primeiro.", file=sys.stderr)
        return 1

    from core.db import connect
    conn = connect(vault)

    # Check clusters exist
    cluster_count = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    if cluster_count == 0:
        print("Erro: nenhum cluster encontrado. Rode 'cluster' primeiro.", file=sys.stderr)
        return 1

    distribution = _load_folder_cluster_distribution(conn, vault)
    if not distribution:
        print("Erro: nenhuma nota encontrada no DB.", file=sys.stderr)
        return 1

    proposals = _propose_folder_areas(distribution)
    created_slugs = _persist_discovered_areas(conn, proposals)

    # Build list of discovered areas pra render CLAUDE.md preview
    discovered_areas = [
        {"slug": p["area_slug"], "label": p["area_label"], "note_count": p["total"]}
        for p in proposals if p["status"] == "clear"
    ]
    claude_preview = _render_claude_md(discovered_areas)

    out_path = _write_proposal_md(vault, proposals, discovered_areas, claude_preview)

    # Report
    n_clear = sum(1 for p in proposals if p["status"] == "clear")
    n_ambiguous = sum(1 for p in proposals if p["status"] == "ambiguous")
    n_noise = sum(1 for p in proposals if p["status"] == "noise_heavy")
    print(f"Propose OK. Pastas analisadas: {len(proposals)}")
    print(f"  {n_clear} com dominante >=60% (mapeadas)")
    print(f"  {n_ambiguous} ambiguas (decida manualmente)")
    print(f"  {n_noise} com majoria noise (sem mapping)")
    print(f"  {len(created_slugs)} novas areas registradas: {', '.join(created_slugs) or '(nenhuma)'}")
    print(f"  Proposta: {out_path}")
    print("  Edite o arquivo se quiser, depois rode 'plan'.")
    return 0


# ---------------------------------------------------------------------------
# Wave 5: plan + approve
# ---------------------------------------------------------------------------
def _iso_now():
    import datetime as _dt
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_proposal_overrides(proposal_path: pathlib.Path) -> dict[str, str]:
    """Parse a tabela '## Mapeamento pasta -> area' e extrai folder -> slug.

    Aceita linhas com slug em backticks, e.g. `| Foo | 5 | X | 80% | `slug` | clear |`.
    Linhas com `_(decidir)_` ou `_(ruido)_` sao ignoradas (usuario nao decidiu).
    """
    import re as _re
    content = proposal_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    in_table = False
    header_seen = False
    overrides: dict[str, str] = {}
    for line in lines:
        if line.startswith("## Mapeamento pasta"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break  # end of section
        if in_table and line.startswith("|"):
            if "---" in line:
                header_seen = True
                continue
            if not header_seen:
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) < 6:
                continue
            folder = parts[0]
            area_cell = parts[4]
            m = _re.match(r"`([a-z0-9\-]+)`", area_cell)
            if m:
                overrides[folder] = m.group(1)
    return overrides


def _ensure_areas_from_overrides(conn, overrides: dict[str, str]):
    """Se o usuario adicionou slugs novos no proposal.md, registra em areas."""
    now = _iso_now()
    with conn:
        for folder, slug in overrides.items():
            exists = conn.execute("SELECT id FROM areas WHERE slug=?", (slug,)).fetchone()
            if exists:
                continue
            is_canonical = 1 if slug in (
                "pessoal", "profissional", "pesquisa", "ai-memory"
            ) else 0
            conn.execute(
                """INSERT INTO areas(slug, label, folder, is_canonical, sensitive, created_at)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (slug, folder, folder, is_canonical, now),
            )


def cmd_plan(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    db_path = vault / ".obsidian-master" / "db.sqlite"
    if not db_path.exists():
        print("Erro: DB nao existe. Rode 'shadow-scan' -> 'cluster' -> 'propose' primeiro.",
              file=sys.stderr)
        return 1

    from core.db import connect
    conn = connect(vault)

    # Check propose step has been run
    areas = conn.execute(
        "SELECT slug, label, folder FROM areas WHERE is_canonical=0"
    ).fetchall()
    if not areas:
        print("Erro: nenhuma area descoberta. Rode 'propose' primeiro.", file=sys.stderr)
        return 1

    # Load proposal.md overrides se existir
    proposal_path = vault / ".obsidian-master" / "migration-proposal.md"
    user_overrides: dict[str, str] = {}
    if proposal_path.exists():
        user_overrides = _parse_proposal_overrides(proposal_path)
        if user_overrides:
            print(f"  Overrides lidos de {proposal_path.name}: "
                  f"{len(user_overrides)} pastas.")

    # Folder -> area_slug map
    folder_to_slug = {row[2]: row[0] for row in areas}  # from DB (clear ones)
    folder_to_slug.update(user_overrides)  # user-edited wins

    # Garante que todas as areas dos overrides existem em `areas`
    _ensure_areas_from_overrides(conn, user_overrides)

    # Clear existing pending plan (idempotency)
    with conn:
        conn.execute("DELETE FROM migration_plan WHERE status='pending'")

    # Generate plan entries
    rows = conn.execute("""
        SELECT n.id, n.path, n.title, cn.cluster_id, c.label
        FROM notes n
        LEFT JOIN cluster_notes cn ON cn.note_id = n.id
        LEFT JOIN clusters c ON c.id = cn.cluster_id
        WHERE n.deleted_at IS NULL
        ORDER BY n.path
    """).fetchall()

    clear_folders = {row[2] for row in areas}
    plan_entries = []
    for nid, path, title, cluster_id, cluster_label in rows:
        top_folder = path.split("/", 1)[0] if "/" in path else "(raiz)"
        area_slug = folder_to_slug.get(top_folder)
        if not area_slug:
            # Pasta nao mapeada: skip (usuario decide manualmente)
            continue

        current_location = path
        # Preserva subpath interno relativo ao folder
        rest = path.split("/", 1)[1] if "/" in path else path
        proposed_location = f"{area_slug}/{rest}"
        if proposed_location == current_location:
            continue  # nao precisa mover

        # Confidence + reason
        if cluster_id is None:
            confidence = 0.2
            reason = (f"Nota em pasta '{top_folder}' (area '{area_slug}'), sem cluster "
                      "(outlier). Movimento baseado so na pasta.")
        else:
            confidence = 0.8 if top_folder in clear_folders else 0.5
            reason = (f"Nota em pasta '{top_folder}' com cluster dominante "
                      f"'{cluster_label}' (area '{area_slug}').")

        plan_entries.append({
            "note_id": nid,
            "note_path": path,
            "current_location": current_location,
            "proposed_location": proposed_location,
            "reason": reason,
            "confidence": confidence,
        })

    # Batch em lotes de 20
    batch_size = 20
    with conn:
        for i, entry in enumerate(plan_entries):
            batch_id = (i // batch_size) + 1
            conn.execute(
                """INSERT INTO migration_plan(note_path, current_location, proposed_location,
                                              reason, confidence, batch_id, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                (entry["note_path"], entry["current_location"],
                 entry["proposed_location"], entry["reason"],
                 entry["confidence"], batch_id),
            )

    total = len(plan_entries)
    n_batches = (total + batch_size - 1) // batch_size
    print(f"Plan OK. {total} notas pra mover em {n_batches} batch(es) de ate {batch_size}.")
    print(f"  Status atual: {total} pending")
    print(f"  Proximo: 'approve --batch 1' (aprovacao interativa) ou "
          f"'approve --batch all' (aprovar tudo de uma vez).")
    return 0


def cmd_approve(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    db_path = vault / ".obsidian-master" / "db.sqlite"
    if not db_path.exists():
        print("Erro: DB nao existe. Rode 'plan' primeiro.", file=sys.stderr)
        return 1

    from core.db import connect
    conn = connect(vault)

    # Identify batch(es)
    if args.batch == "all":
        total = conn.execute(
            "SELECT COUNT(*) FROM migration_plan WHERE status='pending'"
        ).fetchone()[0]
        if total == 0:
            print("Nenhum item pending em migration_plan.")
            return 0
        print(f"Voce vai aprovar em MASSA {total} movimentos de notas.")
        c1 = input("Tem certeza? [y/N]: ").strip().lower()
        if c1 not in ("y", "yes", "s", "sim"):
            print("Abortado.")
            return 1
        c2 = input("Confirme de novo: aprovar TODOS? [y/N]: ").strip().lower()
        if c2 not in ("y", "yes", "s", "sim"):
            print("Abortado.")
            return 1
        with conn:
            conn.execute(
                "UPDATE migration_plan SET status='approved', decided_at=? "
                "WHERE status='pending'",
                (_iso_now(),),
            )
        print(f"OK, {total} movimentos aprovados.")
        return 0

    # Specific batch
    try:
        batch_id = int(args.batch)
    except ValueError:
        print(f"Erro: --batch deve ser inteiro ou 'all', got '{args.batch}'",
              file=sys.stderr)
        return 1

    rows = conn.execute(
        """SELECT id, note_path, current_location, proposed_location, reason, confidence
           FROM migration_plan WHERE batch_id=? AND status='pending'
           ORDER BY id""",
        (batch_id,),
    ).fetchall()
    if not rows:
        print(f"Nenhum item pending no batch {batch_id}.")
        return 0

    print(f"Batch {batch_id}: {len(rows)} movimentos pra revisar.")
    print("Comandos por item: [y]es / [n]o / [a]ll-yes-from-here / [s]kip-remaining")
    print("")

    approve_rest = False
    skip_rest = False
    decisions: dict[int, str] = {}
    for i, (rec_id, note_path, curr, prop, reason, conf) in enumerate(rows):
        if skip_rest:
            break
        if approve_rest:
            decisions[rec_id] = "approved"
            continue
        print(f"[{i+1}/{len(rows)}] {note_path}")
        print(f"  de:  {curr}")
        print(f"  pra: {prop}")
        print(f"  confianca: {conf:.2f}")
        print(f"  motivo: {reason}")
        while True:
            ans = input("  [y/n/a/s]? ").strip().lower()
            if ans in ("y", "yes", "sim"):
                decisions[rec_id] = "approved"
                break
            elif ans in ("n", "no", "nao", "não"):
                decisions[rec_id] = "rejected"
                break
            elif ans in ("a", "all"):
                approve_rest = True
                decisions[rec_id] = "approved"
                break
            elif ans in ("s", "skip", "pula"):
                skip_rest = True
                break
            else:
                print("  Resposta invalida. Use y, n, a, s.")

    # Persist decisions
    now = _iso_now()
    with conn:
        for rec_id, status in decisions.items():
            conn.execute(
                "UPDATE migration_plan SET status=?, decided_at=? WHERE id=?",
                (status, now, rec_id),
            )

    n_approved = sum(1 for v in decisions.values() if v == "approved")
    n_rejected = sum(1 for v in decisions.values() if v == "rejected")
    n_skipped = len(rows) - len(decisions)
    print(f"\nBatch {batch_id} decidido: {n_approved} aprovados, "
          f"{n_rejected} rejeitados, {n_skipped} skipped (ainda pending).")
    return 0


# ---------------------------------------------------------------------------
# Wave 6: apply + rollback
# ---------------------------------------------------------------------------
def cmd_apply(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    db_path = vault / ".obsidian-master" / "db.sqlite"
    if not db_path.exists():
        print("Erro: DB nao existe.", file=sys.stderr)
        return 1
    from core.db import connect
    conn = connect(vault)

    # Check prior batches
    if args.batch == "all":
        batches = sorted({r[0] for r in conn.execute(
            "SELECT DISTINCT batch_id FROM migration_plan WHERE status='approved'"
        ).fetchall()})
        if not batches:
            print("Nenhum batch com itens approved.")
            return 0
    else:
        try:
            b = int(args.batch)
        except ValueError:
            print("Erro: --batch deve ser int ou 'all'", file=sys.stderr)
            return 1
        # Enforce order: earlier batches must be fully applied or rolled_back
        earlier_pending = conn.execute(
            "SELECT COUNT(*) FROM migration_plan "
            "WHERE batch_id < ? AND status='approved'",
            (b,),
        ).fetchone()[0]
        if earlier_pending > 0:
            print(f"Erro: batch(es) anteriores ainda tem {earlier_pending} items "
                  f"'approved' nao aplicados. Aplique em ordem.", file=sys.stderr)
            return 1
        batches = [b]

    total_applied = 0
    for batch_id in batches:
        n = _apply_batch(conn, vault, batch_id)
        total_applied += n
        print(f"Batch {batch_id}: {n} notas movidas.")

    # If all approved batches across all time are now applied, write marker
    remaining_approved = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE status='approved'"
    ).fetchone()[0]
    if remaining_approved == 0:
        total_applied_ever = conn.execute(
            "SELECT COUNT(*) FROM migration_plan WHERE status='applied'"
        ).fetchone()[0]
        if total_applied_ever > 0:
            _write_marker(vault, completed=True)
            print("Marker atualizado: migration_completed=true.")

    # Regenerate _INDEX.md via librarian
    _try_run_librarian(vault)

    return 0


def _apply_batch(conn, vault: pathlib.Path, batch_id: int) -> int:
    """Aplica todos os 'approved' do batch. Retorna quantos foram movidos."""
    rows = conn.execute(
        """SELECT id, note_path, current_location, proposed_location
           FROM migration_plan WHERE batch_id=? AND status='approved'""",
        (batch_id,),
    ).fetchall()
    if not rows:
        return 0

    now = _iso_now()
    today = now[:10]

    # Map old -> new paths for wikilink refactor step
    path_rewrites = {}
    renamed = []

    for plan_id, note_path, curr, prop in rows:
        src = vault / curr
        dst = vault / prop
        if not src.exists():
            print(f"Aviso: fonte {src} nao existe (ja movida ou deletada). Pulando.",
                  file=sys.stderr)
            continue
        if dst.exists():
            print(f"Erro: destino {dst} ja existe. Abortando batch.", file=sys.stderr)
            # Mark as failed via metadata, leave status=approved so rerun can resolve
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        renamed.append((plan_id, curr, prop))
        path_rewrites[curr] = prop

    # Update DB: notes.path + migration_plan.status
    with conn:
        for plan_id, curr, prop in renamed:
            # Update notes.path
            note_row = conn.execute(
                "SELECT id FROM notes WHERE path=? AND deleted_at IS NULL", (curr,)
            ).fetchone()
            note_id = note_row[0] if note_row else None
            if note_id is not None:
                conn.execute(
                    "UPDATE notes SET path=?, indexed_at=? WHERE id=?",
                    (prop, now, note_id),
                )
            conn.execute(
                "UPDATE migration_plan SET status='applied', applied_at=? WHERE id=?",
                (now, plan_id),
            )
            # Emit event
            conn.execute(
                "INSERT INTO events(note_id, event_type, ts, date, metadata_json) "
                "VALUES (?, 'note_moved', ?, ?, ?)",
                (note_id, now, today, json.dumps({"from": curr, "to": prop})),
            )

    # Wikilink refactor: scan bodies for [[old_path]] tokens that need rewriting
    _refactor_wikilinks(vault, path_rewrites, reverse=False)

    return len(renamed)


def _refactor_wikilinks(vault: pathlib.Path, rewrites: dict,
                        reverse: bool = False) -> int:
    """Atualiza wikilinks que referenciam OLD -> NEW path em TODOS os .md do vault.

    Heuristica: procura '[[OLD]]' ou '[[OLD|' com OLD = current_location SEM extensao.
    Para Obsidian o convencional e '[[Nota]]' (title-based) — esses NAO precisam refactor.
    Mas '[[pasta/subpasta/nota]]' (path-based) sim.

    reverse=True usa rewrites como {new: old} pro rollback.
    """
    import re as _re
    if not rewrites:
        return 0

    # Strip .md extension for the targets we look for in [[]]
    pairs = []
    for old, new in rewrites.items():
        old_key = old[:-3] if old.endswith(".md") else old
        new_key = new[:-3] if new.endswith(".md") else new
        pairs.append((old_key, new_key))

    # Build regex patterns
    # [[OLD]] or [[OLD|alias]] -> [[NEW]] / [[NEW|alias]]
    updated = 0
    for md_path in vault.rglob("*.md"):
        # Skip ignored dirs
        rel = md_path.relative_to(vault)
        if any(part in {".obsidian", ".trash", ".obsidian-master", "_templates", ".git"}
               or part.startswith(".") for part in rel.parts):
            continue
        try:
            text = md_path.read_text(encoding="utf-8")
        except Exception:
            continue
        original = text
        for old_key, new_key in pairs:
            pattern = _re.compile(r"\[\[" + _re.escape(old_key) + r"(\||\]\])")
            text = pattern.sub(r"[[" + new_key + r"\1", text)
        if text != original:
            md_path.write_text(text, encoding="utf-8")
            updated += 1
    return updated


def _try_run_librarian(vault: pathlib.Path) -> None:
    """Regenera _INDEX.md via librarian; silent se indisponivel."""
    import subprocess
    librarian = pathlib.Path(__file__).resolve().parents[2] / \
        "obsidian-librarian" / "scripts" / "update_index.py"
    if not librarian.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(librarian), "--vault", str(vault), "--quiet"],
            check=False, timeout=60,
        )
    except Exception:
        pass  # best effort


def _write_marker(vault: pathlib.Path, completed: bool = True) -> None:
    marker = vault / ".obsidian-master" / "marker.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    from importlib.metadata import version as _v, PackageNotFoundError
    try:
        kit_ver = _v("obsidian-master-kit")
    except PackageNotFoundError:
        kit_ver = "0.1.0+dev"
    data = {
        "kit_version": kit_ver,
        "initialized_at": _iso_now(),
        "migration_completed": completed,
    }
    marker.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def cmd_rollback(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    db_path = vault / ".obsidian-master" / "db.sqlite"
    if not db_path.exists():
        print("Erro: DB nao existe.", file=sys.stderr)
        return 1
    from core.db import connect
    conn = connect(vault)

    try:
        batch_id = int(args.batch)
    except ValueError:
        print("Erro: --batch deve ser inteiro", file=sys.stderr)
        return 1

    rows = conn.execute(
        """SELECT id, note_path, current_location, proposed_location
           FROM migration_plan WHERE batch_id=? AND status='applied'""",
        (batch_id,),
    ).fetchall()
    if not rows:
        print(f"Nenhum item 'applied' no batch {batch_id}. Nada pra reverter.")
        return 0

    # Reverse each rename
    now = _iso_now()
    today = now[:10]
    reverted = []
    path_rewrites = {}  # now: new -> old (reverse)

    for plan_id, note_path, curr, prop in rows:
        src = vault / prop  # is currently at proposed
        dst = vault / curr  # restore to current
        if not src.exists():
            print(f"Aviso: {src} nao existe (ja revertida ou deletada). Pulando.",
                  file=sys.stderr)
            continue
        if dst.exists():
            print(f"Erro: destino {dst} ja existe. Conflito. Pulando.", file=sys.stderr)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        reverted.append((plan_id, curr, prop))
        path_rewrites[prop] = curr

    with conn:
        for plan_id, curr, prop in reverted:
            note_row = conn.execute(
                "SELECT id FROM notes WHERE path=?", (prop,)
            ).fetchone()
            note_id = note_row[0] if note_row else None
            if note_id is not None:
                conn.execute(
                    "UPDATE notes SET path=?, indexed_at=? WHERE id=?",
                    (curr, now, note_id),
                )
            conn.execute(
                "UPDATE migration_plan SET status='rolled_back', applied_at=NULL WHERE id=?",
                (plan_id,),
            )
            conn.execute(
                "INSERT INTO events(note_id, event_type, ts, date, metadata_json) "
                "VALUES (?, 'note_moved', ?, ?, ?)",
                (note_id, now, today,
                 json.dumps({"from": prop, "to": curr, "rollback": True})),
            )

    # Reverse wikilinks
    updated = _refactor_wikilinks(vault, path_rewrites, reverse=True)
    print(f"Batch {batch_id}: {len(reverted)} notas revertidas, "
          f"{updated} arquivos com wikilinks refatorados.")

    # Se rollback fez algum batch ficar sem applied, remove migration_completed=true
    remaining_applied = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE status='applied'"
    ).fetchone()[0]
    if remaining_applied == 0:
        marker = vault / ".obsidian-master" / "marker.json"
        if marker.exists():
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
                data["migration_completed"] = False
                marker.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass

    return 0


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

    # Wave 4: propose
    p_pr = sub.add_parser("propose", help="Gera migration-proposal.md + CLAUDE.md preview")
    p_pr.add_argument("--vault", required=True)
    p_pr.set_defaults(func=cmd_propose)

    # Wave 5: plan + approve
    p_pl = sub.add_parser("plan", help="Gera migration_plan em lotes de 20 notas")
    p_pl.add_argument("--vault", required=True)
    p_pl.set_defaults(func=cmd_plan)

    p_ap = sub.add_parser("approve", help="Approval interativo por batch (y/n/a/s)")
    p_ap.add_argument("--vault", required=True)
    p_ap.add_argument("--batch", required=True,
                      help="Numero do batch (1, 2, ...) ou 'all' (aprovar todos)")
    p_ap.set_defaults(func=cmd_approve)

    # Wave 6: apply + rollback
    p_apl = sub.add_parser("apply", help="Aplica renames do batch (apos approval)")
    p_apl.add_argument("--vault", required=True)
    p_apl.add_argument("--batch", required=True,
                       help="Numero do batch ou 'all' pra aplicar todos aprovados")
    p_apl.set_defaults(func=cmd_apply)

    p_rb = sub.add_parser("rollback", help="Reverte renames de um batch ja aplicado")
    p_rb.add_argument("--vault", required=True)
    p_rb.add_argument("--batch", required=True, help="Numero do batch a reverter")
    p_rb.set_defaults(func=cmd_rollback)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
