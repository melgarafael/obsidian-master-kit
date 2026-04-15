#!/usr/bin/env python3
"""Scaffolds an Obsidian vault following the obsidian-master-kit convention.

Idempotent: never overwrites existing files. Copies the bundled template tree from
`../assets/vault-template/` to the target path, interpolating a fixed set of
placeholders with owner-provided values.

Usage is driven by flags; the interactive interview happens upstream (in the skill
prompt). See `../SKILL.md` for the full flow.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Iterable

KIT_VERSION = "0.1.0-mvp"

# Only these placeholders get interpolated at scaffold time. Everything else
# (e.g. {{DATE}}, {{TITULO}} in templates) is preserved for the user to fill in
# when duplicating a template.
SCAFFOLD_PLACEHOLDERS = {
    "OWNER_NAME",
    "OWNER_PROFESSION",
    "OWNER_LANG",
    "OWNER_TIMEZONE",
    "OWNER_TONE",
    "OWNER_AREAS_BULLETS",
    "OWNER_PROJECTS_BULLETS",
    "OWNER_PROJECTS_LINKS",
    "DATE_TODAY",
    "VAULT_NAME",
    "KIT_VERSION",
}

# Per-stub placeholders (replaced when generating project/area stubs):
STUB_PLACEHOLDERS = {"TITULO", "DATE", "PROJECT_NAME"}

# Paths we refuse to scaffold into without --force.
DANGEROUS_PATHS = {
    pathlib.Path.home(),
    pathlib.Path("/"),
    pathlib.Path("/tmp"),
    pathlib.Path("/Users"),
    pathlib.Path("/home"),
}


@dataclass
class OwnerProfile:
    name: str
    profession: str
    areas: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    lang: str = "pt-br"
    timezone: str = "America/Sao_Paulo"
    tone: str = "casual"
    vault_name: str = ""

    @property
    def areas_bullets(self) -> str:
        if not self.areas:
            return "_(Nenhuma area informada. Edite este arquivo para adicionar.)_"
        return "\n".join(f"- {a}" for a in self.areas)

    @property
    def projects_bullets(self) -> str:
        if not self.projects:
            return "_(Nenhum projeto ativo informado. Edite este arquivo para adicionar.)_"
        return "\n".join(f"- {p}" for p in self.projects)

    @property
    def projects_links(self) -> str:
        if not self.projects:
            return "_(Nenhum projeto ativo. Quando houver, aparece aqui como wiki-link.)_"
        lines = []
        for p in self.projects:
            lines.append(f"- [[01 - Profissional/Projetos/{p}|{p}]]")
        return "\n".join(lines)

    def as_scaffold_map(self) -> dict[str, str]:
        return {
            "OWNER_NAME": self.name,
            "OWNER_PROFESSION": self.profession,
            "OWNER_LANG": self.lang,
            "OWNER_TIMEZONE": self.timezone,
            "OWNER_TONE": self.tone,
            "OWNER_AREAS_BULLETS": self.areas_bullets,
            "OWNER_PROJECTS_BULLETS": self.projects_bullets,
            "OWNER_PROJECTS_LINKS": self.projects_links,
            "DATE_TODAY": _dt.date.today().isoformat(),
            "VAULT_NAME": self.vault_name or self.name,
            "KIT_VERSION": KIT_VERSION,
        }


def _split_semi(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(";") if x.strip()]


def _load_profile_file(path: pathlib.Path) -> dict:
    """Load a profile file (JSON only in MVP; YAML in v0.2)."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"Profile file {path} must be valid JSON in MVP. Parse error: {e}"
        )


def build_profile(args: argparse.Namespace) -> OwnerProfile:
    data: dict = {}
    if args.profile:
        p = pathlib.Path(args.profile).expanduser().resolve()
        if not p.exists():
            raise SystemExit(f"Profile file not found: {p}")
        data = _load_profile_file(p)

    # CLI flags override profile.
    def pick(flag: str | None, key: str, default=None):
        return flag if flag is not None else data.get(key, default)

    name = pick(args.owner_name, "owner_name")
    profession = pick(args.owner_profession, "owner_profession")
    if not name or not profession:
        raise SystemExit(
            "Missing required owner info. Pass --owner-name and --owner-profession, "
            "or supply them via --profile."
        )

    areas_raw = pick(args.owner_areas, "owner_areas", "")
    projects_raw = pick(args.owner_projects, "owner_projects", "")
    areas = (
        areas_raw
        if isinstance(areas_raw, list)
        else _split_semi(areas_raw or "")
    )
    projects = (
        projects_raw
        if isinstance(projects_raw, list)
        else _split_semi(projects_raw or "")
    )

    return OwnerProfile(
        name=name,
        profession=profession,
        areas=areas,
        projects=projects,
        lang=pick(args.owner_lang, "owner_lang", "pt-br"),
        timezone=pick(args.owner_timezone, "owner_timezone", "America/Sao_Paulo"),
        tone=pick(args.owner_tone, "owner_tone", "casual"),
        vault_name=pick(args.vault_name, "vault_name", ""),
    )


def assert_safe_target(target: pathlib.Path, force: bool) -> None:
    resolved = target.resolve()
    if resolved in DANGEROUS_PATHS and not force:
        raise SystemExit(
            f"Refusing to scaffold in {resolved} without --force. "
            "This looks like a system or home directory, not a vault folder."
        )
    # Reject if target is already a git repo and NOT a vault-master.
    is_git = (resolved / ".git").exists()
    is_vault_master = (resolved / ".obsidian-master" / "marker.json").exists()
    if is_git and not is_vault_master and not force:
        raise SystemExit(
            f"Refusing to scaffold in {resolved}: looks like a code repo (has .git). "
            "Use --force if you really want this."
        )


def interpolate(text: str, mapping: dict[str, str]) -> str:
    """Replace only whitelisted placeholders. Leaves others (e.g. {{DATE}}) intact."""
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key in SCAFFOLD_PLACEHOLDERS and key in mapping:
            return mapping[key]
        return match.group(0)
    return re.sub(r"\{\{([A-Z_]+)\}\}", repl, text)


def interpolate_stub(text: str, mapping: dict[str, str]) -> str:
    """Per-stub interpolation: replaces STUB_PLACEHOLDERS in addition to scaffold ones."""
    combined = SCAFFOLD_PLACEHOLDERS | STUB_PLACEHOLDERS
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key in combined and key in mapping:
            return mapping[key]
        return match.group(0)
    return re.sub(r"\{\{([A-Z_]+)\}\}", repl, text)


def walk_template(root: pathlib.Path) -> Iterable[pathlib.Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # deterministic order for reproducible logs
        dirnames.sort()
        filenames.sort()
        for f in filenames:
            yield pathlib.Path(dirpath) / f


def copy_template_tree(
    template_root: pathlib.Path,
    target: pathlib.Path,
    profile: OwnerProfile,
    dry_run: bool,
) -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    """Copy template tree to target, interpolating scaffold placeholders.

    Returns (created, skipped) lists of relative paths.
    """
    mapping = profile.as_scaffold_map()
    created: list[pathlib.Path] = []
    skipped: list[pathlib.Path] = []

    for src in walk_template(template_root):
        rel = src.relative_to(template_root)
        dst = target / rel

        if dst.exists():
            skipped.append(rel)
            continue

        if dry_run:
            created.append(rel)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in {".md", ".json"}:
            text = src.read_text(encoding="utf-8")
            new_text = interpolate(text, mapping)
            dst.write_text(new_text, encoding="utf-8")
        else:
            shutil.copy2(src, dst)
        created.append(rel)

    return created, skipped


def generate_project_stubs(
    target: pathlib.Path,
    profile: OwnerProfile,
    dry_run: bool,
) -> list[pathlib.Path]:
    template = (
        target / "01 - Profissional" / "_templates" / "Projeto.md"
    )
    if not template.exists():
        return []

    tpl_text = template.read_text(encoding="utf-8")
    today = _dt.date.today().isoformat()
    created = []
    dst_dir = target / "01 - Profissional" / "Projetos"
    dst_dir.mkdir(parents=True, exist_ok=True)

    for project in profile.projects:
        safe_name = project.replace("/", "-").strip()
        dst = dst_dir / f"{safe_name}.md"
        if dst.exists():
            continue
        mapping = {"TITULO": project, "DATE": today}
        new_text = interpolate_stub(tpl_text, mapping)
        if not dry_run:
            dst.write_text(new_text, encoding="utf-8")
        created.append(dst.relative_to(target))
    return created


def generate_area_stubs(
    target: pathlib.Path,
    profile: OwnerProfile,
    dry_run: bool,
) -> list[pathlib.Path]:
    template = target / "01 - Profissional" / "_templates" / "Area.md"
    if not template.exists():
        return []

    tpl_text = template.read_text(encoding="utf-8")
    today = _dt.date.today().isoformat()
    created = []
    dst_dir = target / "01 - Profissional" / "Areas"
    dst_dir.mkdir(parents=True, exist_ok=True)

    for area in profile.areas:
        safe_name = area.replace("/", "-").strip()
        dst = dst_dir / f"{safe_name}.md"
        if dst.exists():
            continue
        mapping = {"TITULO": area, "DATE": today}
        new_text = interpolate_stub(tpl_text, mapping)
        if not dry_run:
            dst.write_text(new_text, encoding="utf-8")
        created.append(dst.relative_to(target))
    return created


def find_template_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    candidate = here.parent / "assets" / "vault-template"
    if not candidate.exists():
        raise SystemExit(
            f"Template root not found at {candidate}. Is the plugin installed correctly?"
        )
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold an Obsidian vault following obsidian-master-kit conventions.",
    )
    parser.add_argument("--path", default=".", help="Target directory (default: pwd)")
    parser.add_argument("--owner-name", help="Owner's name")
    parser.add_argument("--owner-profession", help="Owner's profession / function")
    parser.add_argument("--owner-areas", help="Areas separated by `;`")
    parser.add_argument("--owner-projects", help="Active projects separated by `;`")
    parser.add_argument("--owner-lang", help="Journaling language (default: pt-br)")
    parser.add_argument("--owner-timezone", help="IANA timezone (default: America/Sao_Paulo)")
    parser.add_argument("--owner-tone", help="`casual` or `formal` (default: casual)")
    parser.add_argument("--vault-name", help="Human-readable vault name")
    parser.add_argument("--profile", help="JSON file with answers (CLI flags override)")
    parser.add_argument("--dry-run", action="store_true", help="Show plan, don't write")
    parser.add_argument("--force", action="store_true", help="Bypass safety checks")

    args = parser.parse_args(argv)

    target = pathlib.Path(args.path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    assert_safe_target(target, args.force)

    profile = build_profile(args)
    if not profile.vault_name:
        profile.vault_name = target.name

    template_root = find_template_root()

    print(f"Scaffolding vault at: {target}")
    print(f"Template source:      {template_root}")
    print(f"Kit version:          {KIT_VERSION}")
    print(f"Owner:                {profile.name} ({profile.profession})")
    print(f"Areas ({len(profile.areas)}):      {profile.areas or '—'}")
    print(f"Projects ({len(profile.projects)}):  {profile.projects or '—'}")
    if args.dry_run:
        print("DRY RUN — no files will be written.\n")

    created, skipped = copy_template_tree(template_root, target, profile, args.dry_run)
    project_stubs = generate_project_stubs(target, profile, args.dry_run)
    area_stubs = generate_area_stubs(target, profile, args.dry_run)

    print(f"\nCreated {len(created)} files from template.")
    if skipped:
        print(f"Skipped {len(skipped)} pre-existing files (idempotent mode):")
        for s in skipped:
            print(f"  - {s}")
    if project_stubs:
        print(f"\nGenerated {len(project_stubs)} project stub(s) in 01 - Profissional/Projetos/:")
        for s in project_stubs:
            print(f"  + {s}")
    if area_stubs:
        print(f"\nGenerated {len(area_stubs)} area stub(s) in 01 - Profissional/Areas/:")
        for s in area_stubs:
            print(f"  + {s}")

    print("\nNext steps:")
    print(f"  1. Open {target} as a vault in Obsidian (File > Open Vault).")
    print("  2. Read CLAUDE.md and _INDEX.md to get oriented.")
    print("  3. Review 00 - Pessoal/Perfil.md and adjust the bio if needed.")
    print("  4. From now on, the librarian keeps _INDEX.md fresh automatically.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
