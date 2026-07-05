"""jobpulse.database — Database connectivity sub-package.

Responsible for:
    - Creating the SQLAlchemy engine (connection pool)
    - Providing a session factory for database transactions
    - Offering a context manager for safe session lifecycle management

All database interactions in the pipeline should go through this module —
never create ad-hoc connections or engines in extractor/loader modules.

Design Pattern:
    Engine is created once (singleton), Sessions are short-lived per operation.

    ┌──────────────────────────────────────────────────┐
    │  engine = create_db_engine(settings)             │
    │  SessionFactory = get_session_factory(engine)    │
    │                                                  │
    │  with db_session(SessionFactory) as session:     │
    │      session.execute(...)                        │
    └──────────────────────────────────────────────────┘

Typical Usage:
    from jobpulse.database.engine import create_db_engine, get_session_factory
    from jobpulse.database.session import db_session
"""
