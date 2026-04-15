---
name: add-new-skill-or-feature-module
description: Workflow command scaffold for add-new-skill-or-feature-module in obsidian-master-kit.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /add-new-skill-or-feature-module

Use this workflow when working on **add-new-skill-or-feature-module** in `obsidian-master-kit`.

## Goal

Introduces a new skill or major feature module, including shell/CLI, documentation, and initial tests.

## Common Files

- `skills/<skill-name>/SKILL.md`
- `skills/<skill-name>/scripts/<feature>.py`
- `core/<utility>.py`
- `tests/test_<feature>_cli_shell.py`
- `tests/test_core_<utility>.py`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Create or update SKILL.md with frontmatter and usage documentation.
- Implement initial CLI or script file(s) with argparse or similar stub logic.
- Add or update core utility modules as needed for shared functionality.
- Write initial test files covering CLI, argument parsing, and core logic.
- Verify regression tests and code coverage.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.