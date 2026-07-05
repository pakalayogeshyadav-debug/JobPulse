"""jobpulse.utils — Shared utility functions sub-package.

Contains reusable, stateless helper functions used across multiple
pipeline modules. Utilities have NO business logic — they are pure
technical helpers.

Organisation:
    utils/
    ├── date_utils.py     → Date parsing, formatting, timezone helpers
    ├── file_utils.py     → File I/O, path resolution, directory creation
    ├── string_utils.py   → Text cleaning, normalisation, slugification
    └── retry_utils.py    → Tenacity retry decorators

Rules for Utilities:
    - Must be PURE FUNCTIONS (no side effects, no database calls)
    - Must have complete type hints and docstrings
    - Must be covered by unit tests in tests/test_utils.py
    - Must NOT import from other jobpulse sub-packages (to avoid circular imports)

Usage:
    from jobpulse.utils.string_utils import clean_text
    from jobpulse.utils.date_utils import parse_posted_date
    from jobpulse.utils.file_utils import ensure_directory
"""
