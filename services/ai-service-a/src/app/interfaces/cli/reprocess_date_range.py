"""
CLI: reprocess_date_range.py
Usage: python -m src.app.interfaces.cli.reprocess_date_range --start 2026-05-01 --end 2026-05-03
"""
import argparse
import logging
import re
import sys
import uuid
from datetime import date

from src.app.bootstrap import bootstrap

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date(s: str) -> date:
    if not _DATE_RE.match(s):
        raise argparse.ArgumentTypeError(f"Date must be YYYY-MM-DD, got: {s!r}")
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocess comments for a date range")
    parser.add_argument("--start", required=True, type=_parse_date, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_parse_date, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    container = bootstrap()
    cid = str(uuid.uuid4())

    try:
        result = container.reprocess_date_range_use_case.execute(
            start_date=args.start,
            end_date=args.end,
            correlation_id=cid,
        )
    except (PermissionError, ValueError) as exc:
        logger.error("reprocess_date_range_rejected", extra={"reason": str(exc)})
        sys.exit(1)

    if result.status == "failed":
        logger.error("reprocess_failed", extra={"error": result.error_message})
        sys.exit(1)

    logger.info(
        "reprocess_date_range_complete",
        extra={"total_updated": result.total_updated, "correlation_id": cid},
    )


if __name__ == "__main__":
    main()
