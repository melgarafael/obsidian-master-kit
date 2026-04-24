#!/usr/bin/env python3
"""CLI entry do obsidian-forge."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _detectar_vault(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / ".obsidian-master" / "marker.json").exists():
            return cand
    raise FileNotFoundError("Vault nao encontrado. Use --vault PATH.")


def cmd_scan(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from scan_context import scan, init_config
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()

    if args.init:
        print("Quais pastas o forge deve vigiar? (ENTER duplo termina)")
        pastas: list[str] = []
        while True:
            try:
                linha = input("> ").strip()
            except EOFError:
                break
            if not linha:
                break
            p = Path(linha).expanduser()
            if not p.exists():
                print(f"  pasta inexistente: {p}")
                continue
            pastas.append(str(p))
        if not pastas:
            print("Nenhuma pasta. Abortado.")
            return 1
        cfg = init_config(vault_root=vault, pastas=pastas)
        print(f"Config salvo: {cfg}")
        return 0

    if args.add:
        from frontmatter import read_frontmatter, write_frontmatter
        cfg_path = vault / "04 - Negocio" / "_config-scan.md"
        if not cfg_path.exists():
            print("Rode --init antes.")
            return 1
        meta, body = read_frontmatter(cfg_path)
        pastas = list(meta.get("pastas_observadas", []))
        if args.add not in pastas:
            pastas.append(args.add)
            meta["pastas_observadas"] = pastas
            write_frontmatter(cfg_path, meta, body)
            print(f"Adicionado: {args.add}")
        return 0

    try:
        scan(vault_root=vault, silent=args.silent, quick=args.quick)
        return 0
    except FileNotFoundError as e:
        print(f"Erro: {e}")
        return 1


def cmd_plan(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from plan_business import ler_estado, limpar_estado
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()

    if args.status:
        plano = vault / "04 - Negocio" / "_plano.md"
        if not plano.exists():
            print("Nenhum plano ativo. Rode `forge plan`.")
            return 0
        from frontmatter import read_frontmatter
        meta, _ = read_frontmatter(plano)
        print(f"Plano · ciclo {meta.get('ciclo')} · {meta.get('status')}")
        print(f"  Produto: {meta.get('produto')}")
        print(f"  Problema: {meta.get('problema')}")
        print(f"  Pessoa: {meta.get('pessoa')}")
        return 0

    if args.new_cycle:
        import shutil
        from datetime import datetime
        area = vault / "04 - Negocio"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        arq = area / "acoes" / "_arquivados" / stamp
        arq.mkdir(parents=True, exist_ok=True)
        for f in ["_plano.md", "_metas.md"]:
            src = area / f
            if src.exists():
                shutil.move(str(src), str(arq / f))
        for f in (area / "acoes").glob("[0-9]*.md"):
            shutil.move(str(f), str(arq / f.name))
        limpar_estado(vault)
        print(f"Ciclo arquivado em {arq}.")
        return 0

    estado = ler_estado(vault)
    passo = estado.get("passo_atual", 0) + 1
    print(f"Estado: passo_atual={estado.get('passo_atual', 0)}. Proximo: {passo}.")
    print("Use --save-plano, --save-metas, --save-acoes (o Claude Code conduz o chat).")
    return 0


def cmd_plan_save_plano(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from plan_business import renderizar_plano, ler_estado, salvar_estado
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()
    respostas = json.loads(Path(args.respostas).read_text(encoding="utf-8"))
    renderizar_plano(vault_root=vault, respostas=respostas)
    e = ler_estado(vault)
    e["passo_atual"] = 2
    e["resp_plano"] = respostas
    salvar_estado(vault, e)
    print("OK _plano.md.")
    return 0


def cmd_plan_save_metas(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from plan_business import renderizar_metas, ler_estado, salvar_estado
    from math_funil import validar_funil, FunilInvalido
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()
    r = json.loads(Path(args.respostas).read_text(encoding="utf-8"))
    funil = [
        {"etapa": "clientes", "alvo": r["clientes_alvo"], "valor_unitario": r["valor_unitario"]},
        {"etapa": "reunioes", "alvo": r["reunioes_alvo"], "taxa_conversao": r["reunioes_taxa"]},
        {"etapa": "leads", "alvo": r["leads_alvo"], "taxa_conversao": r["leads_taxa"]},
        {"etapa": "alcance", "alvo": r["alcance_alvo"], "fonte": r["alcance_fonte"]},
    ]
    try:
        validar_funil(funil, valor_alvo=r["valor_alvo"])
    except FunilInvalido as exc:
        print(f"Validacao falhou: {exc}")
        return 1
    renderizar_metas(vault_root=vault, respostas=r)
    e = ler_estado(vault)
    e["passo_atual"] = 3
    e["resp_metas"] = r
    salvar_estado(vault, e)
    print("OK _metas.md.")
    return 0


def cmd_plan_save_acoes(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from plan_business import renderizar_acoes, ler_estado, salvar_estado
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()
    criados = renderizar_acoes(vault_root=vault)
    e = ler_estado(vault)
    e["passo_atual"] = 4
    salvar_estado(vault, e)
    print(f"OK {len(criados)} acoes criadas.")
    return 0


def cmd_dash(args: argparse.Namespace) -> int:
    import http.server
    import socketserver
    import threading
    import webbrowser

    sys.path.insert(0, str(Path(__file__).parent))
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()
    scripts_dir = Path(__file__).parent

    if args.refresh:
        from dash_refresh import recomputar
        recomputar(vault_root=vault)
        print("OK _metas.md recalculado.")
        return 0

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(scripts_dir), **kw)
        def log_message(self, *a, **kw):
            if args.verbose:
                super().log_message(*a, **kw)
        def do_POST(self):
            if self.path == '/scan':
                try:
                    from scan_context import scan
                    result = scan(vault_root=vault, silent=True, quick=True)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode())
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(404)

    class LocalOnly(socketserver.TCPServer):
        allow_reuse_address = True

    port = args.port
    with LocalOnly(('127.0.0.1', port), Handler) as srv:
        url = f'http://127.0.0.1:{port}/dashboard.html'
        print(f'forge dash · {url}')
        print(f'  vault: {vault}')
        print('  Ctrl-C pra parar.')
        if not args.no_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\nparando.')
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge")
    p.add_argument("--vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("scan")
    ps.add_argument("--init", action="store_true")
    ps.add_argument("--silent", action="store_true")
    ps.add_argument("--quick", action="store_true")
    ps.add_argument("--add")
    ps.set_defaults(func=cmd_scan)

    pp = sub.add_parser("plan")
    pp.add_argument("--status", action="store_true")
    pp.add_argument("--new-cycle", action="store_true")
    pp.set_defaults(func=cmd_plan)

    for nome, fn in [("plan-save-plano", cmd_plan_save_plano),
                     ("plan-save-metas", cmd_plan_save_metas),
                     ("plan-save-acoes", cmd_plan_save_acoes)]:
        sp = sub.add_parser(nome)
        if nome != "plan-save-acoes":
            sp.add_argument("--respostas", required=True)
        sp.set_defaults(func=fn)

    pd = sub.add_parser("dash")
    pd.add_argument("--port", type=int, default=4712)
    pd.add_argument("--no-browser", action="store_true")
    pd.add_argument("--refresh", action="store_true")
    pd.add_argument("--verbose", action="store_true")
    pd.set_defaults(func=cmd_dash)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
