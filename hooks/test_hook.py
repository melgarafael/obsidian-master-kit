#!/usr/bin/env python3
"""Standalone integration test pro hook PostToolUse (Epic 03 S05).

Nao usa pytest. Roda `python3 hooks/test_hook.py` do repo root. Imprime
PASS/FAIL por cenario + latency report. Exit 0 se todos passam, 1 se
qualquer falhar.

Cenarios cobertos:
    1. Vault v0.1.1 (sem DB) -> signal-only, exit 0
    2. Vault v1.0 (com DB) + Write -> event emitido + additionalContext
    3. Write fora de qualquer vault -> no-op (exit 0, sem stdout)
    4. Dedup 5s -> 2 writes no mesmo vault dentro de 5s = 1 additionalContext
    5. Latency p50/p99 em 10 invocacoes warm DB (target <100ms)
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "post-vault-write.py"
CORE_DIR = REPO_ROOT / "core"


# ---------- test fixtures ----------

def _make_v01_vault(tmpdir: pathlib.Path) -> pathlib.Path:
    """v0.1.1 vault: marker.json presente, sem db.sqlite."""
    vault = tmpdir / "vault_v01"
    (vault / ".obsidian-master").mkdir(parents=True)
    (vault / ".obsidian-master" / "marker.json").write_text(
        json.dumps({"version": "0.1.1"})
    )
    return vault


def _make_v10_vault(tmpdir: pathlib.Path) -> pathlib.Path:
    """v1.0 vault: marker + DB inicializado via core.db.connect.

    Carregamos core.db sem executar core/__init__.py (mesmo truque do hook).
    """
    vault = tmpdir / "vault_v10"
    (vault / ".obsidian-master").mkdir(parents=True)
    (vault / ".obsidian-master" / "marker.json").write_text(
        json.dumps({"version": "1.0.0"})
    )
    # area canonica pra que notas sob ela recebam area_id no scanner
    (vault / "00 - Pessoal").mkdir()

    # Inicializa schema via core.db (isolado)
    import importlib.util
    import types

    pkg = types.ModuleType("core")
    pkg.__path__ = [str(CORE_DIR)]
    sys.modules.setdefault("core", pkg)

    for mod_name, fname in [("parser", "parser.py"), ("db", "db.py")]:
        qualified = f"core.{mod_name}"
        if qualified in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(qualified, CORE_DIR / fname)
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
        setattr(sys.modules["core"], mod_name, module)

    core_db = sys.modules["core.db"]
    conn = core_db.connect(vault)
    conn.close()
    return vault


def _invoke_hook(vault: pathlib.Path | None, file_path: pathlib.Path) -> tuple[int, str, str]:
    """Roda o hook como subprocess (como o Claude Code harness faria).
    Retorna (returncode, stdout, stderr)."""
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(file_path)},
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _write_note(vault: pathlib.Path, rel: str, content: str) -> pathlib.Path:
    note = vault / rel
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(content)
    return note


def _read_events(vault: pathlib.Path) -> list[tuple[str, int | None]]:
    db = vault / ".obsidian-master" / "db.sqlite"
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT event_type, note_id FROM events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return rows


# ---------- test cases ----------

def test_1_v01_signal_only(tmpdir: pathlib.Path) -> bool:
    vault = _make_v01_vault(tmpdir)
    note = _write_note(vault, "note.md", "hello")
    rc, stdout, stderr = _invoke_hook(vault, note)
    if rc != 0:
        print(f"  FAIL: returncode={rc}, stderr={stderr[:200]}")
        return False
    # Deve emitir additionalContext (signal-only path)
    if not stdout.strip():
        print("  FAIL: expected additionalContext, got empty stdout")
        return False
    try:
        out = json.loads(stdout)
    except Exception as e:
        print(f"  FAIL: stdout not JSON: {e}")
        return False
    if "additionalContext" not in out.get("hookSpecificOutput", {}):
        print(f"  FAIL: additionalContext missing: {out}")
        return False
    # Nao deve ter criado DB
    if (vault / ".obsidian-master" / "db.sqlite").exists():
        print("  FAIL: v0.1.1 vault nao deveria ter DB criado")
        return False
    return True


def test_2_v10_event_emitted(tmpdir: pathlib.Path) -> bool:
    vault = _make_v10_vault(tmpdir)
    note = _write_note(vault, "00 - Pessoal/nota.md", "# Nota\nconteudo")

    rc, stdout, stderr = _invoke_hook(vault, note)
    if rc != 0:
        print(f"  FAIL: returncode={rc}, stderr={stderr[:200]}")
        return False

    # additionalContext esperado
    if not stdout.strip():
        print("  FAIL: expected additionalContext stdout")
        return False
    out = json.loads(stdout)
    if "additionalContext" not in out.get("hookSpecificOutput", {}):
        print(f"  FAIL: additionalContext missing: {out}")
        return False

    # Event esperado na tabela events (note_created)
    events = _read_events(vault)
    note_events = [e for e in events if e[0].startswith("note_")]
    if not note_events:
        print(f"  FAIL: nenhum note_* event emitido; events={events}")
        return False
    if note_events[0][0] != "note_created":
        print(f"  FAIL: esperava note_created, got {note_events[0][0]}")
        return False
    return True


def test_3_outside_vault(tmpdir: pathlib.Path) -> bool:
    # Arquivo num tmpdir sem marker
    outside = tmpdir / "random"
    outside.mkdir()
    note = outside / "foo.md"
    note.write_text("fora de vault")

    rc, stdout, stderr = _invoke_hook(None, note)
    if rc != 0:
        print(f"  FAIL: returncode={rc}, stderr={stderr[:200]}")
        return False
    if stdout.strip():
        print(f"  FAIL: esperava stdout vazio, got: {stdout[:200]}")
        return False
    return True


def test_4_dedup_window(tmpdir: pathlib.Path) -> bool:
    vault = _make_v10_vault(tmpdir)
    note = _write_note(vault, "00 - Pessoal/dedup.md", "primeiro")

    rc1, stdout1, _ = _invoke_hook(vault, note)
    # Segunda write imediatamente apos — dentro do dedup window
    note.write_text("segundo")
    rc2, stdout2, _ = _invoke_hook(vault, note)

    if rc1 != 0 or rc2 != 0:
        print(f"  FAIL: rc1={rc1}, rc2={rc2}")
        return False

    if not stdout1.strip():
        print("  FAIL: primeiro invocacao deveria emitir additionalContext")
        return False
    if stdout2.strip():
        print(f"  FAIL: segunda invocacao dentro de 5s NAO deveria emitir: {stdout2[:200]}")
        return False
    return True


def test_5_latency(tmpdir: pathlib.Path) -> tuple[bool, float, float]:
    vault = _make_v10_vault(tmpdir)
    # Pre-popula uma nota pra warm DB (schema ja exists, cache OS quente)
    note = _write_note(vault, "00 - Pessoal/warm.md", "pre-populate")
    _invoke_hook(vault, note)
    # Reset dedupe tracker pro hook emitir sempre (mede full-path)
    tracker = vault / ".obsidian-master" / "last-hook.txt"
    if tracker.exists():
        tracker.unlink()

    durations: list[float] = []
    for i in range(10):
        # usa paths diferentes pra forcar trabalho real no scanner (note_created em cada)
        n = _write_note(vault, f"00 - Pessoal/bench{i}.md", f"# bench {i}\nbody")
        if tracker.exists():
            tracker.unlink()  # bypass dedup pra medir full latency cada vez
        t0 = time.perf_counter()
        rc, _, stderr = _invoke_hook(vault, n)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if rc != 0:
            print(f"  FAIL iter {i}: rc={rc} stderr={stderr[:200]}")
            return False, 0.0, 0.0
        durations.append(dt_ms)

    durations.sort()
    p50 = statistics.median(durations)
    # p99 de 10 amostras: usa o max (aprox conservador)
    p99 = durations[-1]
    print(f"  Latency samples (ms): {[round(d, 1) for d in durations]}")
    print(f"  p50={p50:.1f}ms  p99={p99:.1f}ms  (target <100ms)")
    passed = p99 < 100.0
    return passed, p50, p99


# ---------- runner ----------

def main() -> int:
    tests = [
        ("1. v0.1.1 vault (sem DB) -> signal-only", test_1_v01_signal_only),
        ("2. v1.0 vault + Write -> event + additionalContext", test_2_v10_event_emitted),
        ("3. Write fora de vault -> no-op", test_3_outside_vault),
        ("4. Dedup window 5s preservado", test_4_dedup_window),
    ]

    failures = 0
    for name, fn in tests:
        print(f"[RUN]  {name}")
        with tempfile.TemporaryDirectory() as td:
            ok = fn(pathlib.Path(td))
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {name}\n")
        if not ok:
            failures += 1

    # Latency test (returns extra data)
    print("[RUN]  5. Latency p50/p99 < 100ms em warm DB")
    with tempfile.TemporaryDirectory() as td:
        ok, p50, p99 = test_5_latency(pathlib.Path(td))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] 5. Latency p50={p50:.1f}ms p99={p99:.1f}ms\n")
    if not ok:
        failures += 1

    total = len(tests) + 1
    print(f"=== {total - failures}/{total} passed ===")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
