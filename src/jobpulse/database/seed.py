"""jobpulse.database.seed — Database seeder.

Seeds reference dimension tables (employment_types, experience_levels)
with required lookup values. Idempotent and safe to run on every startup.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from jobpulse.logging.logger import get_logger

logger = get_logger(__name__)


def seed_reference_data(engine: Engine) -> None:
    """Seed reference dimension tables with initial values.
    
    Uses INSERT ... ON CONFLICT DO NOTHING to ensure idempotency.
    
    Args:
        engine: SQLAlchemy Engine connected to PostgreSQL.
    """
    logger.info("Seeding reference data...")
    
    queries = [
        # Employment Types
        """
        INSERT INTO public.employment_types (type_code, type_label, description) VALUES
            ('FULL_TIME',   'Full-time',   'Standard permanent employment, typically 35-40 hours/week'),
            ('PART_TIME',   'Part-time',   'Employment for fewer hours than a standard full-time schedule'),
            ('CONTRACT',    'Contract',    'Fixed-term engagement, often through a staffing agency'),
            ('INTERNSHIP',  'Internship',  'Temporary position, typically for students or recent graduates'),
            ('FREELANCE',   'Freelance',   'Self-employed, project-based engagement'),
            ('TEMPORARY',   'Temporary',   'Short-term employment to cover a specific need')
        ON CONFLICT (type_code) DO NOTHING;
        """,
        # Experience Levels
        """
        INSERT INTO public.experience_levels 
            (level_code, level_label, min_years_experience, max_years_experience, sort_order)
        VALUES
            ('ENTRY',     'Entry Level',  0,    2,    1),
            ('MID',       'Mid-Level',    2,    5,    2),
            ('SENIOR',    'Senior',       5,    10,   3),
            ('LEAD',      'Lead',         8,    15,   4),
            ('EXECUTIVE', 'Executive',    12,   NULL, 5)
        ON CONFLICT (level_code) DO NOTHING;
        """
    ]

    with engine.connect() as conn:
        with conn.begin():
            for query in queries:
                conn.execute(text(query))
                
    logger.info("Reference data seeded successfully.")
