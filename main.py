"""
JobPulse Pipeline Entry Point.

This module serves as the top-level entry point for the JobPulse ETL pipeline.
It orchestrates the full Extract -> Transform -> Load cycle.

Usage:
    Run directly:   python main.py
    
    With CLI args:
        python main.py --full (default)
        python main.py --extract-only (Future)
        python main.py --transform-only (Future)
        python main.py --load-only (Future)
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the src/ directory is on PYTHONPATH when running main.py directly.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jobpulse.config.settings import get_settings
from jobpulse.database.engine import create_db_engine, get_session_factory
from jobpulse.logging.logger import get_logger, setup_logging
from jobpulse.pipeline.orchestrator import PipelineOrchestrator


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="JobPulse ETL Pipeline")
    parser.add_argument(
        "--full", action="store_true", default=True,
        help="Run the complete Extract -> Transform -> Load pipeline."
    )
    parser.add_argument(
        "--extract-only", action="store_true",
        help="Run only the extraction phase (Not yet implemented)."
    )
    parser.add_argument(
        "--transform-only", action="store_true",
        help="Run only the transformation phase (Not yet implemented)."
    )
    parser.add_argument(
        "--load-only", action="store_true",
        help="Run only the loading phase (Not yet implemented)."
    )
    return parser.parse_args()


def main() -> None:
    """
    Main entry point for the JobPulse ETL pipeline.

    Loads configuration, initialises the logger, and kicks off the pipeline.
    Returns specific exit codes:
        0 = SUCCESS
        1 = FAILURE
        2 = PARTIAL SUCCESS
    """
    args = parse_args()
    settings = get_settings()
    
    # Configure logging with a unique file per execution
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = PROJECT_ROOT / "logs" / f"{timestamp}.log"
    
    setup_logging(level=settings.log_level, log_file=log_file)
    logger = get_logger(__name__)

    logger.info("=" * 60)
    logger.info("JobPulse Pipeline Starting")
    logger.info("=" * 60)
    
    # Handle unimplemented isolated modes gracefully
    if args.extract_only or args.transform_only or args.load_only:
        logger.error("Isolated pipeline stages are not yet implemented. Please run with --full")
        sys.exit(1)

    try:
        logger.info("Environment : %s", settings.environment)
        logger.info("Log Level   : %s", settings.log_level)
        logger.info("Database    : %s@%s:%s/%s",
                    settings.db_user,
                    settings.db_host,
                    settings.db_port,
                    settings.db_name)

        # Initialize database engine and session factory
        engine = create_db_engine(settings)
        session_factory = get_session_factory(engine)

        # Initialize and run the pipeline orchestrator
        orchestrator = PipelineOrchestrator(settings=settings, session_factory=session_factory)
        report = orchestrator.run()

        # Exit with correct status code
        if report.status == "SUCCESS":
            logger.info("Pipeline completed successfully.")
            sys.exit(0)
        elif report.status == "PARTIAL SUCCESS":
            logger.warning("Pipeline completed with partial success (some rows failed to load).")
            sys.exit(2)
        else:
            logger.error("Pipeline failed during execution.")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user (KeyboardInterrupt).")
        sys.exit(1)

    except Exception as exc:
        logger.exception("Unhandled exception in pipeline: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
