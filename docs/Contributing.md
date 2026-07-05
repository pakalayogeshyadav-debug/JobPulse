# Contributing to JobPulse

We welcome contributions to JobPulse! Please follow these guidelines to ensure a smooth review process.

## Branching Strategy

We use GitHub Flow:
- `main` is the stable, deployable branch.
- Feature branches should be created off `main` and named descriptively: `feature/adzuna-extractor`, `bugfix/salary-parsing`.

## Code Quality Standards

JobPulse enforces strict CI/CD quality gates. Your code will not be merged unless it passes all checks.

1. **Formatting:** We use `black`. Run `black src tests` before committing.
2. **Linting:** We use `ruff`. Run `ruff check src tests` to catch unused imports and PEP8 violations.
3. **Type Hints:** All function signatures must include Python type hints. We enforce this via `mypy src tests`.
4. **Testing:** New features must include `pytest` unit tests. Overall test coverage must remain > 80%.

## Pull Request Process

1. Fork the repository and create your branch from `main`.
2. Write clear, documented code following the SOLID principles.
3. Add unit tests for your logic.
4. Ensure the test suite passes locally (`pytest`).
5. Open a Pull Request. Provide a clear description of the problem solved and any schema changes required.
6. A maintainer will review your code. 
7. Once approved and CI passes, your branch will be squash-merged into `main`.

## Reporting Bugs
Use GitHub Issues. Include:
- Python version.
- OS version.
- Traceback logs.
- Steps to reproduce.
