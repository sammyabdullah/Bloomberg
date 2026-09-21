"""Extraction of standardized financial line items from SEC XBRL company facts."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

VALID_FORMS = {"10-K", "10-Q"}

# Output column name -> candidate US-GAAP tags, in priority order.
# Different filers use different tags for economically-equivalent concepts;
# for each fiscal period we take the first candidate tag that has a value,
# so a company doesn't get "missing" data just because it uses a synonym tag.
CONCEPT_MAP = {
    "Revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
    ],
    "CostOfRevenue": [
        "CostOfRevenue",
        "CostOfServices",
    ],
    "CostOfGoodsAndServicesSold": [
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "OperatingExpenses": [
        "OperatingExpenses",
        "OperatingCostsAndExpenses",
        "CostsAndExpenses",
    ],
    "ResearchAndDevelopmentExpense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "SellingGeneralAndAdministrativeExpense": [
        "SellingGeneralAndAdministrativeExpense",
        "SellingGeneralAndAdministrativeExpenses",
        "GeneralAndAdministrativeExpense",
    ],
    "NetIncomeLoss": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
}

METRIC_COLUMNS = list(CONCEPT_MAP.keys())


def build_ticker_cik_map(tickers_json: dict) -> dict:
    """Build TICKER -> zero-padded 10-digit CIK string from company_tickers.json."""
    mapping = {}
    for entry in tickers_json.values():
        try:
            ticker = str(entry.get("ticker", "")).upper()
            cik = entry.get("cik_str")
            if ticker and cik is not None:
                mapping[ticker] = f"{int(cik):010d}"
        except (TypeError, ValueError):
            continue
    return mapping


def _period_label(rec: dict) -> str:
    fy = rec.get("fy")
    fp = rec.get("fp")
    if fp == "FY" or (fp is None and rec.get("form") == "10-K"):
        return f"FY{fy}" if fy else (rec.get("end") or "")
    if fy and fp:
        return f"{fp} FY{fy}"
    return rec.get("end") or ""


def _extract_concept_periods(facts: dict, candidates: list) -> dict:
    """Return {(start, end, fy, fp): raw_fact_record} for the first matching tag per period."""
    us_gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    periods = {}
    for tag in candidates:
        node = us_gaap.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        for unit_name, entries in units.items():
            for e in entries:
                if e.get("form") not in VALID_FORMS:
                    continue
                end = e.get("end")
                if not end:
                    continue
                key = (e.get("start"), end, e.get("fy"), e.get("fp"))
                existing = periods.get(key)
                if existing is None:
                    periods[key] = {**e, "tag": tag, "unit": unit_name}
                elif existing.get("tag") == tag:
                    # Same tag reported this period twice (e.g. restated as a
                    # comparative in a later filing) -- keep the earliest filing.
                    if (e.get("filed") or "") < (existing.get("filed") or ""):
                        periods[key] = {**e, "tag": tag, "unit": unit_name}
                # else: a higher-priority tag already filled this period; keep it.
    return periods


def extract_ticker_financials(facts: dict, quarters: Optional[int] = None) -> list:
    """Turn a companyfacts JSON blob into a list of per-fiscal-period row dicts.

    Rows are sorted chronologically (oldest first). If `quarters` is given,
    only the most recent N periods are kept.
    """
    per_concept = {}
    for column, candidates in CONCEPT_MAP.items():
        try:
            per_concept[column] = _extract_concept_periods(facts, candidates)
        except (AttributeError, TypeError) as exc:
            logger.warning("Malformed facts while extracting %s: %s", column, exc)
            per_concept[column] = {}

    all_keys = set()
    for periods in per_concept.values():
        all_keys.update(periods.keys())

    if not all_keys:
        return []

    rows = []
    for key in all_keys:
        start, end, fy, fp = key
        sample = None
        for periods in per_concept.values():
            if key in periods:
                sample = periods[key]
                break

        row = {
            "start": start,
            "end": end,
            "fy": fy,
            "fp": fp,
            "form": sample.get("form") if sample else None,
            "filed": sample.get("filed") if sample else None,
            "label": _period_label(sample) if sample else (end or ""),
        }
        for column, periods in per_concept.items():
            rec = periods.get(key)
            row[column] = rec.get("val") if rec else None
        rows.append(row)

    rows.sort(key=lambda r: (r["end"] or "", r["start"] or ""))

    if quarters is not None and quarters > 0:
        rows = rows[-quarters:]

    return rows
