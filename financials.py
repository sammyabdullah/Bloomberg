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

# Income-statement/cash-flow ("duration") concepts, as opposed to
# balance-sheet ("instant") ones. Used to filter out rows that only have a
# stray balance-sheet value attached (e.g. a snapshot re-reported as a
# sequential-quarter comparative in a later filing) with no real
# income-statement or cash-flow data -- not a useful reporting period on its
# own, just an artifact of that snapshot's end date matching a real quarter.
DURATION_CONCEPT_KEYS = [col for col in CONCEPT_MAP if METRIC_STATEMENT.get(col) != STMT_BALANCE]

# A row with fewer than this many populated income-statement/cash-flow
# fields is a candidate to be dropped as a stray if it's too close in time
# to a much richer row (see the stray-row filter in extract_ticker_financials).
RICH_ROW_MIN_DURATION_FIELDS = 3
NEARBY_STRAY_DAYS_THRESHOLD = 60

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


# A candidate duration this long or more is treated as "this end date is a
# fiscal year-end" for the purposes of picking between same-tag duplicates.
ANNUAL_DURATION_THRESHOLD_DAYS = 300


def _extract_concept_periods(facts: dict, candidates: list) -> dict:
    """Return {end_date: raw_fact_record} for the first matching tag per period.

    Facts are keyed by end date ALONE. Neither SEC's computed "fy"/"fp"
    fields nor the reporting "form" are reliable enough to key on: both can
    differ *across different concepts, or across different appearances of
    the exact same real period*. fy/fp can be assigned inconsistently for
    different line items describing the same real quarter (its original
    filing vs. a later prior-year-comparative appearance). form has the same
    problem in a different guise: e.g. a fiscal year-end balance sheet value
    is reported with form="10-K" in the original annual filing, but the same
    real date's balance sheet also reappears as the prior-year-end
    comparative column inside the *next* 10-Q, carrying form="10-Q" even
    though it describes the same date. Keying on either field fragments one
    true period into multiple sparse rows. The end date itself is the one
    thing that's consistent across every appearance of the same real period,
    and it also naturally lines up a balance-sheet "instant" fact (no start
    date) with income-statement/cash-flow "duration" facts (start+end)
    ending on that same date.

    A single tag can carry more than one duration fact for the same end
    date: e.g. a 10-Q commonly tags both the standalone 3-month figure and
    the 6-month year-to-date cumulative figure under the same concept. When
    that happens, we keep the shorter duration UNLESS one of the candidates
    looks like a full fiscal year (>= ANNUAL_DURATION_THRESHOLD_DAYS), in
    which case we keep the longer one -- since that means this end date is a
    fiscal year-end and the long duration is the real annual figure, not a
    footnote breakout. Instant facts (no duration at all) and remaining
    ties (equal duration -- e.g. a genuine restatement) fall back to keeping
    the earliest-filed value, which correctly prefers an original filing's
    balance-sheet snapshot over a later comparative reappearance of it.
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
                if e.get("form") not in VALID_FORMS:
                    continue
                end = e.get("end")
                if not end:
                    continue
                existing = periods.get(end)
                if existing is None:
                    periods[end] = {**e, "tag": tag, "unit": unit_name}
                    continue
                if existing.get("tag") != tag:
                    # A higher-priority tag already filled this period; keep it.
                    continue

                existing_days = _duration_days(existing)
                new_days = _duration_days(e)
                prefer_new = False
                if new_days is not None and new_days != existing_days:
                    if max(new_days, existing_days or 0) >= ANNUAL_DURATION_THRESHOLD_DAYS:
                        prefer_new = existing_days is None or new_days > existing_days
                    else:
                        prefer_new = existing_days is None or new_days < existing_days
                elif new_days == existing_days and (e.get("filed") or "") < (existing.get("filed") or ""):
                    prefer_new = True

                if prefer_new:
                    periods[end] = {**e, "tag": tag, "unit": unit_name}
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
    for end in all_keys:
        # Use whichever concept's fact for this period was filed earliest as
        # the canonical source for display metadata (form/fy/fp/label) --
        # that's normally the period's original filing rather than a later
        # restatement or comparative appearance, so it gives the most
        # sensible label even though fy/fp/form are no longer used for
        # grouping.
        candidates_for_key = [periods[end] for periods in per_concept.values() if end in periods]
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
            "form": sample.get("form") if sample else None,
            "filed": sample.get("filed") if sample else None,
            "label": _period_label(sample) if sample else (end or ""),
        }
        for column, periods in per_concept.items():
            rec = periods.get(end)
            row[column] = rec.get("val") if rec else None
        rows.append(row)

    # Drop rows with no income-statement or cash-flow data at all -- a row
    # holding only a stray balance-sheet value (see DURATION_CONCEPT_KEYS
    # above) isn't a useful reporting period, just leftover from a snapshot
    # incidentally re-reported for that same end date in a later filing.
    rows = [row for row in rows if any(row.get(col) is not None for col in DURATION_CONCEPT_KEYS)]

    rows.sort(key=lambda r: (r["end"] or "", r["start"] or ""))

    # Drop sparse rows that sit suspiciously close in time to a much richer
    # row -- real fiscal quarters are ~90 days apart, so an end date that
    # lands within ~60 days of another, far more complete row's end date is
    # very unlikely to be its own standalone reporting period; more likely
    # it's some incidental duration fact (e.g. a one-off disclosure tied to
    # a specific transaction or award-modification date) that happened to
    # get tagged with metadata resembling a fiscal period.
    def _duration_field_count(row):
        return sum(1 for col in DURATION_CONCEPT_KEYS if row.get(col) is not None)

    end_dates = []
    for row in rows:
        try:
            end_dates.append(date.fromisoformat(row["end"]) if row.get("end") else None)
        except ValueError:
            end_dates.append(None)

    kept_rows = []
    for i, row in enumerate(rows):
        count = _duration_field_count(row)
        is_stray = False
        if count < RICH_ROW_MIN_DURATION_FIELDS and end_dates[i] is not None:
            for j, other in enumerate(rows):
                if i == j or end_dates[j] is None:
                    continue
                if (
                    abs((end_dates[j] - end_dates[i]).days) <= NEARBY_STRAY_DAYS_THRESHOLD
                    and _duration_field_count(other) > count
                ):
                    is_stray = True
                    break
        if not is_stray:
            kept_rows.append(row)
    rows = kept_rows

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
