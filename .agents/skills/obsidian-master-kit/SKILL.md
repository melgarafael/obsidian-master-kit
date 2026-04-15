```markdown
# obsidian-master-kit Development Patterns

> Auto-generated skill from repository analysis

## Overview

The `obsidian-master-kit` repository provides a modular Python toolkit for building and extending skills (feature modules) for Obsidian workflows. It emphasizes clear conventions for file structure, code style, and collaborative workflows, enabling rapid development, integration, and testing of new features and CLI utilities.

## Coding Conventions

- **File Naming:**  
  Use `snake_case` for all Python files and modules.
  ```
  skills/my_skill/scripts/generate.py
  core/text_utils.py
  ```

- **Import Style:**  
  Prefer **relative imports** within packages.
  ```python
  from .utils import parse_args
  from ..core.text_utils import normalize_text
  ```

- **Export Style:**  
  Use **named exports** (explicitly define what is exported).
  ```python
  __all__ = ["main", "parse_args"]
  ```

- **Commit Messages:**  
  Follow **conventional commit** format, primarily using the `feat` prefix.
  ```
  feat: add knn-based note suggestion engine
  ```

## Workflows

### Add New Skill or Feature Module
**Trigger:** When you want to add a new skill or major feature module to the system  
**Command:** `/new-skill`

1. Create or update `SKILL.md` in `skills/<skill-name>/` with frontmatter and usage docs.
2. Implement initial CLI or script file(s) in `skills/<skill-name>/scripts/`, using `argparse` or similar for stubs.
   ```python
   # skills/my_skill/scripts/generate.py
   import argparse

   def main():
       parser = argparse.ArgumentParser(description="Generate notes")
       # add arguments...
       args = parser.parse_args()
       # stub logic

   if __name__ == "__main__":
       main()
   ```
3. Add or update core utility modules in `core/` as needed.
4. Write initial test files (e.g., `tests/test_generate_cli_shell.py`) covering CLI, argument parsing, and core logic.
5. Run regression tests and check code coverage.

### Feature Implementation with Tests
**Trigger:** When adding a new algorithm, detector, or engine to an existing skill/module  
**Command:** `/add-feature`

1. Create or update the main script implementing the feature (e.g., `knn.py`, `gaps.py`).
2. Write or update corresponding test files with unit and integration cases.
   ```python
   # tests/test_knn.py
   from skills.my_skill.scripts.knn import knn_search

   def test_knn_basic():
       # test logic
   ```
3. Update CLI wiring or main entrypoint to expose the new feature.
4. Ensure regression tests pass and maintain coverage.

### CLI Wireup and End-to-End Integration
**Trigger:** When exposing new functionality through the CLI and validating E2E behavior  
**Command:** `/wire-cli`

1. Update CLI script (e.g., `expand.py`) to wire up new or existing subcommands.
   ```python
   # skills/my_skill/scripts/expand.py
   import argparse

   def main():
       parser = argparse.ArgumentParser()
       subparsers = parser.add_subparsers(dest="command")
       # add subcommands
       args = parser.parse_args()
       # dispatch logic

   if __name__ == "__main__":
       main()
   ```
2. Update or rewrite CLI shell tests to cover argument parsing and feature invocation.
3. Add or update integration tests for end-to-end flows.
4. Check regression and coverage.

### Extend Feature with Integration and Indexing
**Trigger:** When integrating a feature with other modules (e.g., librarian, MOC linking)  
**Command:** `/integrate-feature`

1. Update feature implementation to add integration logic (e.g., linking to MOC, triggering indexing).
2. Update or add tests for integration scenarios, including deduplication and error handling.
3. Ensure frontmatter and output formats remain consistent.
4. Run regression tests to confirm E2E flow.

## Testing Patterns

- **Test File Naming:**  
  Use `test_<feature>.py` for unit tests and `test_<feature>_cli_shell.py` for CLI/shell tests.
  ```
  tests/test_generate.py
  tests/test_generate_cli_shell.py
  ```

- **Test Structure:**  
  While the specific framework is unknown, tests are typically organized by feature and cover both unit and integration scenarios.
  ```python
  def test_feature_behavior():
      # Arrange
      # Act
      # Assert
  ```

- **CLI Testing:**  
  CLI scripts are tested via shell-style tests simulating argument parsing and command execution.

## Commands

| Command        | Purpose                                                         |
|----------------|-----------------------------------------------------------------|
| /new-skill     | Scaffold a new skill or major feature module                    |
| /add-feature   | Add a new algorithm or feature to an existing module with tests |
| /wire-cli      | Wire up CLI and ensure end-to-end integration                   |
| /integrate-feature | Integrate a feature with other modules and update tests     |
```
