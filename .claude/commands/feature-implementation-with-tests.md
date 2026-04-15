---
name: feature-implementation-with-tests
description: Workflow command scaffold for feature-implementation-with-tests in obsidian-master-kit.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /feature-implementation-with-tests

Use this workflow when working on **feature-implementation-with-tests** in `obsidian-master-kit`.

## Goal

Implements a new algorithm or feature in an existing module, accompanied by dedicated test coverage.

## Common Files

- `skills/<skill-name>/scripts/<feature>.py`
- `tests/test_<feature>.py`
- `skills/<skill-name>/scripts/expand.py`
- `tests/test_expand_cli_shell.py`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Create or update the main script file implementing the feature (e.g., knn.py, gaps.py, generate.py).
- Write or update corresponding test files with unit and integration cases.
- Update CLI wiring or main entrypoint to expose the new feature.
- Ensure regression tests pass and coverage is maintained.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.