"""Extraction of standardized financial line items from SEC XBRL company facts."""

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

VALID_FORMS = {"10-K", "10-Q"}

STMT_INCOME = "Income Statement"
STMT_BALANCE = "Balance Sheet"
STMT_CASHFLOW = "Cash Flow"

# Output column name -> candidate US-GAAP tags, in priority order.
# Different filers use different tags for economically-equivalent concepts;
# for each fiscal period we take the first candidate tag that has a value,
# so a company doesn't get "missing" data just because it uses a synonym tag.
#
# Income-statement and cash-flow concepts are "duration" facts (they have a
# start and end date). Balance-sheet concepts are "instant" facts (a snapshot
# as of a single date, no start) -- see _extract_concept_periods for how the
# two are reconciled onto the same row.
CONCEPT_MAP = {
    # ---- Income statement ----
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
    "GrossProfit": [
        "GrossProfit",
    ],
    "ResearchAndDevelopmentExpense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "SellingAndMarketingExpense": [
        "SellingAndMarketingExpense",
        "MarketingExpense",
    ],
    "GeneralAndAdministrativeExpense": [
        "GeneralAndAdministrativeExpense",
    ],
    "SellingGeneralAndAdministrativeExpense": [
        "SellingGeneralAndAdministrativeExpense",
        "SellingGeneralAndAdministrativeExpenses",
    ],
    "OperatingExpenses": [
        "OperatingExpenses",
        "OperatingCostsAndExpenses",
        "CostsAndExpenses",
    ],
    "OperatingIncomeLoss": [
        "OperatingIncomeLoss",
    ],
    "InterestExpense": [
        "InterestExpense",
        "InterestExpenseDebt",
    ],
    "InterestIncome": [
        "InvestmentIncomeInterest",
        "InterestIncomeOther",
    ],
    "OtherNonoperatingIncomeExpense": [
        "OtherNonoperatingIncomeExpense",
    ],
    "IncomeLossBeforeIncomeTaxes": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "IncomeTaxExpenseBenefit": [
        "IncomeTaxExpenseBenefit",
    ],
    "NetIncomeLoss": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "EarningsPerShareBasic": [
        "EarningsPerShareBasic",
    ],
    "EarningsPerShareDiluted": [
        "EarningsPerShareDiluted",
    ],
    "WeightedAverageSharesBasic": [
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
    "WeightedAverageSharesDiluted": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ],
    "ShareBasedCompensation": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
    ],
    "DepreciationDepletionAndAmortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ],
    # ---- Balance sheet (instant facts -- see note above) ----
    "CashAndCashEquivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "ShortTermInvestments": [
        "ShortTermInvestments",
    ],
    "AccountsReceivableNet": [
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    ],
    "InventoryNet": [
        "InventoryNet",
    ],
    "AssetsCurrent": [
        "AssetsCurrent",
    ],
    "PropertyPlantAndEquipmentNet": [
        "PropertyPlantAndEquipmentNet",
    ],
    "Goodwill": [
        "Goodwill",
    ],
    "IntangibleAssetsNet": [
        "FiniteLivedIntangibleAssetsNet",
        "IntangibleAssetsNetExcludingGoodwill",
    ],
    "Assets": [
        "Assets",
    ],
    "AccountsPayableCurrent": [
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ],
    "DeferredRevenueCurrent": [
        "ContractWithCustomerLiabilityCurrent",
        "DeferredRevenueCurrent",
    ],
    "LiabilitiesCurrent": [
        "LiabilitiesCurrent",
    ],
    "LongTermDebtNoncurrent": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
    "Liabilities": [
        "Liabilities",
    ],
    "RetainedEarningsAccumulatedDeficit": [
        "RetainedEarningsAccumulatedDeficit",
    ],
    "StockholdersEquity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "LiabilitiesAndStockholdersEquity": [
        "LiabilitiesAndStockholdersEquity",
    ],
    # ---- Cash flow statement ----
    "NetCashProvidedByUsedInOperatingActivities": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "NetCashProvidedByUsedInInvestingActivities": [
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    ],
    "NetCashProvidedByUsedInFinancingActivities": [
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
    ],
    "PaymentsToAcquirePropertyPlantAndEquipment": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ],
    "PaymentsForRepurchaseOfCommonStock": [
        "PaymentsForRepurchaseOfCommonStock",
    ],
    "PaymentsOfDividends": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ],
}

# Which financial statement each column belongs to, for grouping in Excel.
# Must cover every key in CONCEPT_MAP.
METRIC_STATEMENT = {
    "Revenue": STMT_INCOME,
    "CostOfRevenue": STMT_INCOME,
    "CostOfGoodsAndServicesSold": STMT_INCOME,
    "GrossProfit": STMT_INCOME,
    "ResearchAndDevelopmentExpense": STMT_INCOME,
    "SellingAndMarketingExpense": STMT_INCOME,
    "GeneralAndAdministrativeExpense": STMT_INCOME,
    "SellingGeneralAndAdministrativeExpense": STMT_INCOME,
    "OperatingExpenses": STMT_INCOME,
    "OperatingIncomeLoss": STMT_INCOME,
    "InterestExpense": STMT_INCOME,
    "InterestIncome": STMT_INCOME,
    "OtherNonoperatingIncomeExpense": STMT_INCOME,
    "IncomeLossBeforeIncomeTaxes": STMT_INCOME,
    "IncomeTaxExpenseBenefit": STMT_INCOME,
    "NetIncomeLoss": STMT_INCOME,
    "EarningsPerShareBasic": STMT_INCOME,
    "EarningsPerShareDiluted": STMT_INCOME,
    "WeightedAverageSharesBasic": STMT_INCOME,
    "WeightedAverageSharesDiluted": STMT_INCOME,
    "ShareBasedCompensation": STMT_INCOME,
    "DepreciationDepletionAndAmortization": STMT_INCOME,
    "CashAndCashEquivalents": STMT_BALANCE,
    "ShortTermInvestments": STMT_BALANCE,
    "AccountsReceivableNet": STMT_BALANCE,
    "InventoryNet": STMT_BALANCE,
    "AssetsCurrent": STMT_BALANCE,
    "PropertyPlantAndEquipmentNet": STMT_BALANCE,
    "Goodwill": STMT_BALANCE,
    "IntangibleAssetsNet": STMT_BALANCE,
    "Assets": STMT_BALANCE,
    "AccountsPayableCurrent": STMT_BALANCE,
    "DeferredRevenueCurrent": STMT_BALANCE,
    "LiabilitiesCurrent": STMT_BALANCE,
    "LongTermDebtNoncurrent": STMT_BALANCE,
    "Liabilities": STMT_BALANCE,
    "RetainedEarningsAccumulatedDeficit": STMT_BALANCE,
    "StockholdersEquity": STMT_BALANCE,
    "LiabilitiesAndStockholdersEquity": STMT_BALANCE,
    "NetCashProvidedByUsedInOperatingActivities": STMT_CASHFLOW,
    "NetCashProvidedByUsedInInvestingActivities": STMT_CASHFLOW,
    "NetCashProvidedByUsedInFinancingActivities": STMT_CASHFLOW,
    "PaymentsToAcquirePropertyPlantAndEquipment": STMT_CASHFLOW,
    "PaymentsForRepurchaseOfCommonStock": STMT_CASHFLOW,
    "PaymentsOfDividends": STMT_CASHFLOW,
}

# Derived columns computed after extraction (not pulled directly from a
# single XBRL fact) -- inserted at a specific position among METRIC_COLUMNS.
DERIVED_AFTER = {
    "Revenue": ["RevenuePriorYear", "RevenueYoYGrowth"],
}
METRIC_STATEMENT["RevenuePriorYear"] = STMT_INCOME
METRIC_STATEMENT["RevenueYoYGrowth"] = STMT_INCOME

# Columns holding a ratio (e.g. 0.15 for 15%) rather than a dollar amount,
# so excel_writer can format them as a percentage instead of "#,##0".
PERCENT_COLUMNS = {"RevenueYoYGrowth"}

METRIC_COLUMNS = []
for _col in CONCEPT_MAP.keys():
    METRIC_COLUMNS.append(_col)
    METRIC_COLUMNS.extend(DERIVED_AFTER.get(_col, []))


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


def _duration_days(rec: dict) -> Optional[int]:
    """Days spanned by a duration fact's start/end. None for instant facts or bad dates."""
    start, end = rec.get("start"), rec.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _extract_concept_periods(facts: dict, candidates: list) -> dict:
    """Return {(end, form): raw_fact_record} for the first matching tag per period.

    Facts are keyed by (end, form) -- the fact's own end date and which
    filing type reported it -- rather than SEC's computed "fy"/"fp" fields.
    Those fields are meant to identify the fiscal period, but SEC can assign
    them inconsistently *across different concepts for the exact same real
    calendar quarter* (e.g. a quarter's original filing vs. its later
    appearance as a prior-year comparative in a subsequent filing can get
    different nominal fy values for different line items) -- keying on that
    would fragment one true period into several sparse rows. The end date
    and form are directly reported per fact and don't have this problem.
    Keying by (end, form) rather than just (end,) also lets a balance-sheet
    "instant" fact (no start date) line up on the same row as
    income-statement/cash-flow "duration" facts (start+end) for the same
    filing, since both share the same end date and form.

    A single tag can carry more than one duration fact for the same (end,
    form): e.g. a 10-Q commonly tags both the standalone 3-month figure and
    the 6-month year-to-date cumulative figure under the same concept. For
    10-Q periods we keep the shortest duration (the standalone quarter, not
    the YTD cumulative); for 10-K periods we keep the longest (the full
    year, not some shorter footnote breakout). Remaining ties (equal
    duration -- e.g. a genuine restatement) fall back to the earliest-filed
    value.
    """
    us_gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    periods = {}
    for tag in candidates:
        node = us_gaap.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        for unit_name, entries in units.items():
            for e in entries:
                form = e.get("form")
                if form not in VALID_FORMS:
                    continue
                end = e.get("end")
                if not end:
                    continue
                key = (end, form)
                existing = periods.get(key)
                if existing is None:
                    periods[key] = {**e, "tag": tag, "unit": unit_name}
                    continue
                if existing.get("tag") != tag:
                    # A higher-priority tag already filled this period; keep it.
                    continue

                existing_days = _duration_days(existing)
                new_days = _duration_days(e)
                prefer_new = False
                if new_days is not None and new_days != existing_days:
                    if form == "10-K":
                        prefer_new = existing_days is None or new_days > existing_days
                    else:
                        prefer_new = existing_days is None or new_days < existing_days
                elif new_days == existing_days and (e.get("filed") or "") < (existing.get("filed") or ""):
                    prefer_new = True

                if prefer_new:
                    periods[key] = {**e, "tag": tag, "unit": unit_name}
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
        end, form = key
        # Use whichever concept's fact for this period was filed earliest as
        # the canonical source for display metadata (fy/fp/label) -- that's
        # normally the period's original filing rather than a later
        # restatement or comparative appearance, so it gives the most
        # sensible label even though fy/fp are no longer used for grouping.
        candidates_for_key = [periods[key] for periods in per_concept.values() if key in periods]
        sample = (
            min(candidates_for_key, key=lambda rec: rec.get("filed") or "9999-99-99")
            if candidates_for_key
            else None
        )

        row = {
            "start": sample.get("start") if sample else None,
            "end": end,
            "fy": sample.get("fy") if sample else None,
            "fp": sample.get("fp") if sample else None,
            "form": form,
            "filed": sample.get("filed") if sample else None,
            "label": _period_label(sample) if sample else (end or ""),
        }
        for column, periods in per_concept.items():
            rec = periods.get(key)
            row[column] = rec.get("val") if rec else None
        rows.append(row)

    # Drop rows with no data at all in any tracked concept -- these are
    # occasional artifacts of a fact appearing under a given (end, form)
    # only as an incidental comparative (e.g. a balance sheet snapshot
    # reappearing in a later filing's comparative column) with nothing else
    # attached to that same key.
    rows = [row for row in rows if any(row.get(col) is not None for col in CONCEPT_MAP)]

    rows.sort(key=lambda r: (r["end"] or "", r["start"] or ""))

    # Look up "same period, roughly one year earlier" by end date (within a
    # small tolerance), using the full history (before --quarters truncation
    # below) so a row near the edge of a truncated window can still find its
    # prior-year comparison. Matching by real elapsed time is more robust
    # than SEC's fy/fp fields, which are no longer used for row identity.
    rows_by_end = {}
    for row in rows:
        rows_by_end.setdefault(row["end"], row)
    for row in rows:
        prior_row = None
        end = row.get("end")
        try:
            end_date = date.fromisoformat(end) if end else None
        except ValueError:
            end_date = None
        if end_date is not None:
            target = end_date - timedelta(days=365)
            best_diff = None
            for other_end, other_row in rows_by_end.items():
                try:
                    other_date = date.fromisoformat(other_end)
                except (ValueError, TypeError):
                    continue
                diff = abs((other_date - target).days)
                if diff <= 10 and (best_diff is None or diff < best_diff):
                    prior_row, best_diff = other_row, diff
        prior_revenue = prior_row.get("Revenue") if prior_row else None
        row["RevenuePriorYear"] = prior_revenue
        revenue = row.get("Revenue")
        if prior_revenue and revenue is not None:
            row["RevenueYoYGrowth"] = (revenue - prior_revenue) / prior_revenue
        else:
            row["RevenueYoYGrowth"] = None

    if quarters is not None and quarters > 0:
        rows = rows[-quarters:]

    return rows
