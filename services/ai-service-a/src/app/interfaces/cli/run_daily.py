"""
CLI: run_daily.py — python -m src.app.interfaces.cli.run_daily
"""
import sys
import uuid
import logging

from src.app.bootstrap import bootstrap

logger = logging.getLogger(__name__)


def main() -> None:
    container = bootstrap()
    cid = str(uuid.uuid4())
    logger.info("cli_run_daily_start", extra={"correlation_id": cid})
    result = container.run_daily_use_case.execute(correlation_id=cid)

    if result.status == "failed":
        logger.error(
            "cli_run_daily_failed",
            extra={"error": result.error_message, "correlation_id": cid},
        )
        sys.exit(1)

    logger.info(
        "cli_run_daily_success",
        extra={
            "total_batches": result.total_batches,
            "total_updated": result.total_updated,
            "correlation_id": cid,
        },
    )


if __name__ == "__main__":
    main()
