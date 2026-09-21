"""Extraction of standardized financial line items from SEC XBRL company facts."""

import logging
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
    """Return {(end, fy, fp): raw_fact_record} for the first matching tag per period.

    Facts are keyed by (end, fy, fp) rather than including "start" so that
    balance-sheet "instant" facts (no start date) line up on the same row as
    income-statement/cash-flow "duration" facts (start+end) for the same
    fiscal period -- both share the same end date, fy, and fp.
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
                key = (end, e.get("fy"), e.get("fp"))
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
        end, fy, fp = key
        sample = None
        for periods in per_concept.values():
            if key in periods:
                sample = periods[key]
                break

        row = {
            "start": sample.get("start") if sample else None,
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
