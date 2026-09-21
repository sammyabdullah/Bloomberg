#!/usr/bin/env python3
"""Pull standardized financials from SEC EDGAR's XBRL APIs into an Excel workbook.

Usage:
    python pull_financials.py --tickers DDOG,BILL,SMAR --output financials.xlsx
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from config import USER_AGENT as CONFIG_USER_AGENT
from excel_writer import write_workbook
from financials import build_ticker_cik_map, extract_ticker_financials
from sec_client import SECClient

logger = logging.getLogger("pull_financials")


def resolve_user_agent(cli_value):
    if cli_value:
        return cli_value
    env_value = os.environ.get("SEC_EDGAR_USER_AGENT")
    if env_value:
        return env_value
    return CONFIG_USER_AGENT


def parse_args():
    parser = argparse.ArgumentParser(
        description="Pull SEC EDGAR XBRL financials into an Excel workbook."
    )
    parser.add_argument(
        "--tickers", required=True, help="Comma-separated list of tickers, e.g. DDOG,BILL,SMAR"
    )
    parser.add_argument(
        "--output", default="financials.xlsx", help="Output .xlsx path (default: financials.xlsx)"
    )
    parser.add_argument(
        "--quarters",
        type=int,
        default=None,
        help="Limit output to the N most recent fiscal periods per ticker (default: all available)",
    )
    parser.add_argument(
        "--cache-dir", default="cache", help="Directory for cached SEC responses (default: ./cache)"
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help="Override the SEC User-Agent header, e.g. 'Jane Doe jane@example.com'",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Ignore local cache and re-download everything from SEC"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose (debug) logging")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    user_agent = resolve_user_agent(args.user_agent)
    try:
        client = SECClient(
            user_agent=user_agent, cache_dir=Path(args.cache_dir), force_refresh=args.refresh
        )
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        logger.error("No tickers provided.")
        sys.exit(1)

    try:
        tickers_json = client.get_company_tickers()
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)
    ticker_cik_map = build_ticker_cik_map(tickers_json)

    results = {}
    for ticker in tickers:
        cik10 = ticker_cik_map.get(ticker)
        if not cik10:
            logger.warning("No CIK found for ticker %s, skipping.", ticker)
            results[ticker] = {"status": "error", "message": "No CIK match", "company_name": ""}
            continue

        logger.info("Fetching %s (CIK %s)...", ticker, cik10)
        try:
            facts = client.get_company_facts(cik10)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the run
            logger.warning("Failed to fetch company facts for %s: %s", ticker, exc)
            results[ticker] = {
                "status": "error",
                "message": f"Fetch failed: {exc}",
                "company_name": "",
            }
            continue

        if facts is None:
            logger.warning("No XBRL company facts available for %s (CIK %s).", ticker, cik10)
            results[ticker] = {
                "status": "error",
                "message": "No XBRL data available",
                "company_name": "",
            }
            continue

        company_name = facts.get("entityName", "") if isinstance(facts, dict) else ""
        try:
            rows = extract_ticker_financials(facts, quarters=args.quarters)
        except Exception as exc:  # noqa: BLE001 - malformed API response must not crash the run
            logger.warning("Failed to parse financials for %s: %s", ticker, exc)
            results[ticker] = {
                "status": "error",
                "message": f"Parse failed: {exc}",
                "company_name": company_name,
            }
            continue

        if not rows:
            logger.warning(
                "No matching 10-K/10-Q concepts found for %s (check ticker or fallback tags).", ticker
            )
            results[ticker] = {
                "status": "error",
                "message": "No matching concepts found",
                "company_name": company_name,
            }
            continue

        results[ticker] = {"status": "ok", "rows": rows, "company_name": company_name}
        logger.info("%s: %d fiscal periods extracted.", ticker, len(rows))

    write_workbook(args.output, results)
    ok_count = sum(1 for r in results.values() if r.get("status") == "ok")
    logger.info("Wrote %s (%d/%d tickers with data)", args.output, ok_count, len(tickers))


if __name__ == "__main__":
    main()
