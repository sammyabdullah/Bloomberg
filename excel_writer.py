"""Writes extracted financials to an Excel workbook (one tab per ticker + Summary)."""

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from financials import METRIC_COLUMNS, METRIC_STATEMENT, STMT_BALANCE, STMT_CASHFLOW, STMT_INCOME

METRIC_HEADERS = {
    "Revenue": "Revenue",
    "CostOfRevenue": "Cost of Revenue",
    "CostOfGoodsAndServicesSold": "Cost of Goods & Services Sold",
    "GrossProfit": "Gross Profit",
    "ResearchAndDevelopmentExpense": "R&D Expense",
    "SellingAndMarketingExpense": "Selling & Marketing Expense",
    "GeneralAndAdministrativeExpense": "G&A Expense",
    "SellingGeneralAndAdministrativeExpense": "SG&A Expense",
    "OperatingExpenses": "Operating Expenses",
    "OperatingIncomeLoss": "Operating Income (Loss)",
    "InterestExpense": "Interest Expense",
    "InterestIncome": "Interest Income",
    "OtherNonoperatingIncomeExpense": "Other Non-Operating Income (Expense)",
    "IncomeLossBeforeIncomeTaxes": "Income (Loss) Before Taxes",
    "IncomeTaxExpenseBenefit": "Income Tax Expense (Benefit)",
    "NetIncomeLoss": "Net Income (Loss)",
    "EarningsPerShareBasic": "EPS (Basic)",
    "EarningsPerShareDiluted": "EPS (Diluted)",
    "WeightedAverageSharesBasic": "Weighted Avg Shares (Basic)",
    "WeightedAverageSharesDiluted": "Weighted Avg Shares (Diluted)",
    "ShareBasedCompensation": "Stock-Based Compensation",
    "DepreciationDepletionAndAmortization": "D&A",
    "CashAndCashEquivalents": "Cash & Cash Equivalents",
    "ShortTermInvestments": "Short-Term Investments",
    "AccountsReceivableNet": "Accounts Receivable, Net",
    "InventoryNet": "Inventory, Net",
    "AssetsCurrent": "Total Current Assets",
    "PropertyPlantAndEquipmentNet": "PP&E, Net",
    "Goodwill": "Goodwill",
    "IntangibleAssetsNet": "Intangible Assets, Net",
    "Assets": "Total Assets",
    "AccountsPayableCurrent": "Accounts Payable",
    "DeferredRevenueCurrent": "Deferred Revenue (Current)",
    "LiabilitiesCurrent": "Total Current Liabilities",
    "LongTermDebtNoncurrent": "Long-Term Debt",
    "Liabilities": "Total Liabilities",
    "RetainedEarningsAccumulatedDeficit": "Retained Earnings (Accum. Deficit)",
    "StockholdersEquity": "Total Stockholders' Equity",
    "LiabilitiesAndStockholdersEquity": "Total Liabilities & Equity",
    "NetCashProvidedByUsedInOperatingActivities": "Cash Flow From Operations",
    "NetCashProvidedByUsedInInvestingActivities": "Cash Flow From Investing",
    "NetCashProvidedByUsedInFinancingActivities": "Cash Flow From Financing",
    "PaymentsToAcquirePropertyPlantAndEquipment": "CapEx",
    "PaymentsForRepurchaseOfCommonStock": "Stock Buybacks",
    "PaymentsOfDividends": "Dividends Paid",
}

HEADER_FONT = Font(bold=True)
GROUP_FONT = Font(bold=True, color="FFFFFF")
NUMBER_FORMAT = "#,##0"
PER_SHARE_COLUMNS = {"EarningsPerShareBasic", "EarningsPerShareDiluted"}
PER_SHARE_FORMAT = "#,##0.00"

GROUP_FILLS = {
    STMT_INCOME: PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid"),
    STMT_BALANCE: PatternFill(start_color="548235", end_color="548235", fill_type="solid"),
    STMT_CASHFLOW: PatternFill(start_color="BF8F00", end_color="BF8F00", fill_type="solid"),
}

INVALID_SHEET_CHARS = set(r"[]:*?/\\")


def _sheet_name(ticker: str) -> str:
    cleaned = "".join(c for c in ticker if c not in INVALID_SHEET_CHARS)
    return cleaned[:31] or "TICKER"


def _write_headers(ws, meta_headers, first_metric_col):
    """Write a two-row header: statement group labels (merged) over metric names."""
    for col, header in enumerate(meta_headers, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)

    col = first_metric_col
    while col <= first_metric_col + len(METRIC_COLUMNS) - 1:
        column_name = METRIC_COLUMNS[col - first_metric_col]
        group = METRIC_STATEMENT.get(column_name)
        span_end = col
        while (
            span_end + 1 <= first_metric_col + len(METRIC_COLUMNS) - 1
            and METRIC_STATEMENT.get(METRIC_COLUMNS[span_end + 1 - first_metric_col]) == group
        ):
            span_end += 1
        group_cell = ws.cell(row=1, column=col, value=group)
        group_cell.font = GROUP_FONT
        group_cell.fill = GROUP_FILLS.get(group, PatternFill())
        group_cell.alignment = Alignment(horizontal="center")
        if span_end > col:
            ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=span_end)
        col = span_end + 1

    for i, column_name in enumerate(METRIC_COLUMNS):
        cell = ws.cell(row=2, column=first_metric_col + i, value=METRIC_HEADERS[column_name])
        cell.font = HEADER_FONT

    ws.freeze_panes = ws.cell(row=3, column=first_metric_col)


def _autosize(ws, total_cols, header_row):
    for col in range(1, total_cols + 1):
        max_len = 0
        header_val = ws.cell(row=header_row, column=col).value
        if header_val:
            max_len = len(str(header_val))
        for row in ws.iter_rows(min_col=col, max_col=col, min_row=header_row + 1):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 2, 40)


def _number_format_for(column_name):
    return PER_SHARE_FORMAT if column_name in PER_SHARE_COLUMNS else NUMBER_FORMAT


def write_workbook(output_path, ticker_results: dict):
    """ticker_results: {ticker: {"status": "ok"|"error", "rows": [...], "company_name": str, "message": str}}"""
    wb = Workbook()
    wb.remove(wb.active)

    summary_meta = ["Ticker", "Company", "Period", "Form", "Period End", "Filed"]
    summary_first_metric_col = len(summary_meta) + 1
    summary_ws = wb.create_sheet("Summary")
    _write_headers(summary_ws, summary_meta, summary_first_metric_col)

    summary_row_idx = 3
    for ticker, result in ticker_results.items():
        status = result.get("status")
        company_name = result.get("company_name", "")
        rows = result.get("rows", [])

        if status != "ok" or not rows:
            summary_ws.cell(row=summary_row_idx, column=1, value=ticker)
            summary_ws.cell(row=summary_row_idx, column=2, value=company_name)
            summary_ws.cell(row=summary_row_idx, column=3, value=result.get("message", "No data"))
            summary_row_idx += 1
            continue

        ws = wb.create_sheet(_sheet_name(ticker))
        ticker_meta = ["Fiscal Period", "Form", "Period Start", "Period End", "Filed"]
        ticker_first_metric_col = len(ticker_meta) + 1
        _write_headers(ws, ticker_meta, ticker_first_metric_col)
        for r, row in enumerate(rows, start=3):
            ws.cell(row=r, column=1, value=row.get("label"))
            ws.cell(row=r, column=2, value=row.get("form"))
            ws.cell(row=r, column=3, value=row.get("start"))
            ws.cell(row=r, column=4, value=row.get("end"))
            ws.cell(row=r, column=5, value=row.get("filed"))
            for c, column in enumerate(METRIC_COLUMNS, start=ticker_first_metric_col):
                val = row.get(column)
                cell = ws.cell(row=r, column=c, value=val)
                if val is not None:
                    cell.number_format = _number_format_for(column)
        _autosize(ws, ticker_first_metric_col + len(METRIC_COLUMNS) - 1, header_row=2)

        latest = rows[-1]
        summary_ws.cell(row=summary_row_idx, column=1, value=ticker)
        summary_ws.cell(row=summary_row_idx, column=2, value=company_name)
        summary_ws.cell(row=summary_row_idx, column=3, value=latest.get("label"))
        summary_ws.cell(row=summary_row_idx, column=4, value=latest.get("form"))
        summary_ws.cell(row=summary_row_idx, column=5, value=latest.get("end"))
        summary_ws.cell(row=summary_row_idx, column=6, value=latest.get("filed"))
        for c, column in enumerate(METRIC_COLUMNS, start=summary_first_metric_col):
            val = latest.get(column)
            cell = summary_ws.cell(row=summary_row_idx, column=c, value=val)
            if val is not None:
                cell.number_format = _number_format_for(column)
        summary_row_idx += 1

    _autosize(summary_ws, summary_first_metric_col + len(METRIC_COLUMNS) - 1, header_row=2)

    wb.save(output_path)
