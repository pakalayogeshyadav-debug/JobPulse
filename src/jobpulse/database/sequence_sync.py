"""jobpulse.database.sequence_sync — Utility to synchronize PostgreSQL sequences.

Runs at startup to ensure SERIAL sequences are perfectly aligned with MAX(id),
preventing UniqueViolation errors when the database receives manual inserts
or during schema migrations.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


def sync_sequences(engine: Engine) -> dict[str, int]:
    """Synchronize all SERIAL sequences with the max ID of their respective tables.

    Args:
        engine: SQLAlchemy Engine connected to PostgreSQL.

    Returns:
        A dictionary mapping 'table_name.column_name' to the new sequence value.
    """
    logger.info("Synchronizing PostgreSQL sequences...")
    sync_results: dict[str, int] = {}

    query = text(
        """
        SELECT 
            table_name, 
            column_name, 
            column_default 
        FROM information_schema.columns 
        WHERE column_default LIKE 'nextval(%'
        AND table_schema = 'public'
        """
    )

    with engine.connect() as conn:
        with conn.begin():
            columns = conn.execute(query).fetchall()

            for table_name, column_name, default_expr in columns:
                # Extract sequence name from "nextval('seq_name'::regclass)"
                start_idx = default_expr.find("'") + 1
                end_idx = default_expr.find("'", start_idx)
                seq_name = default_expr[start_idx:end_idx]

                # Get MAX(id) from the table
                max_val_query = text(f"SELECT MAX({column_name}) FROM public.{table_name}")
                max_val = conn.execute(max_val_query).scalar()

                if max_val is None:
                    max_val = 0

                # Check current sequence value
                seq_val_query = text(
                    "SELECT last_value FROM pg_sequences WHERE schemaname = 'public' AND sequencename = :seq"
                )
                seq_val = conn.execute(seq_val_query, {"seq": seq_name}).scalar()

                if seq_val is None or max_val > seq_val:
                    # Sync required
                    new_val = max(max_val, 1)
                    conn.execute(text(f"SELECT setval('{seq_name}', {new_val}, true)"))
                    sync_results[f"{table_name}.{column_name}"] = new_val
                    logger.info("Synced sequence %s to %d", seq_name, new_val)

    if not sync_results:
        logger.info("All sequences are perfectly aligned. No synchronization needed.")

    return sync_results
