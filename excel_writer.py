"""Writes extracted financials to an Excel workbook (one tab per ticker + Summary)."""

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from financials import METRIC_COLUMNS

METRIC_HEADERS = {
    "Revenue": "Revenue",
    "CostOfRevenue": "Cost of Revenue",
    "CostOfGoodsAndServicesSold": "Cost of Goods & Services Sold",
    "OperatingExpenses": "Operating Expenses",
    "ResearchAndDevelopmentExpense": "R&D Expense",
    "SellingGeneralAndAdministrativeExpense": "SG&A Expense",
    "NetIncomeLoss": "Net Income (Loss)",
}

HEADER_FONT = Font(bold=True)
NUMBER_FORMAT = "#,##0"

INVALID_SHEET_CHARS = set(r"[]:*?/\\")


def _sheet_name(ticker: str) -> str:
    cleaned = "".join(c for c in ticker if c not in INVALID_SHEET_CHARS)
    return cleaned[:31] or "TICKER"


def _write_header(ws, headers):
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
    ws.freeze_panes = "A2"


def _autosize(ws, headers):
    for col, header in enumerate(headers, start=1):
        max_len = len(str(header))
        for row in ws.iter_rows(min_col=col, max_col=col, min_row=2):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 2, 40)


def write_workbook(output_path, ticker_results: dict):
    """ticker_results: {ticker: {"status": "ok"|"error", "rows": [...], "company_name": str, "message": str}}"""
    wb = Workbook()
    wb.remove(wb.active)

    summary_headers = ["Ticker", "Company", "Period", "Form", "Period End", "Filed"] + [
        METRIC_HEADERS[c] for c in METRIC_COLUMNS
    ]
    summary_ws = wb.create_sheet("Summary")
    _write_header(summary_ws, summary_headers)

    summary_row_idx = 2
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
        headers = ["Fiscal Period", "Form", "Period Start", "Period End", "Filed"] + [
            METRIC_HEADERS[c] for c in METRIC_COLUMNS
        ]
        _write_header(ws, headers)
        for r, row in enumerate(rows, start=2):
            ws.cell(row=r, column=1, value=row.get("label"))
            ws.cell(row=r, column=2, value=row.get("form"))
            ws.cell(row=r, column=3, value=row.get("start"))
            ws.cell(row=r, column=4, value=row.get("end"))
            ws.cell(row=r, column=5, value=row.get("filed"))
            for c, column in enumerate(METRIC_COLUMNS, start=6):
                val = row.get(column)
                cell = ws.cell(row=r, column=c, value=val)
                if val is not None:
                    cell.number_format = NUMBER_FORMAT
        _autosize(ws, headers)

        latest = rows[-1]
        summary_ws.cell(row=summary_row_idx, column=1, value=ticker)
        summary_ws.cell(row=summary_row_idx, column=2, value=company_name)
        summary_ws.cell(row=summary_row_idx, column=3, value=latest.get("label"))
        summary_ws.cell(row=summary_row_idx, column=4, value=latest.get("form"))
        summary_ws.cell(row=summary_row_idx, column=5, value=latest.get("end"))
        summary_ws.cell(row=summary_row_idx, column=6, value=latest.get("filed"))
        for c, column in enumerate(METRIC_COLUMNS, start=7):
            val = latest.get(column)
            cell = summary_ws.cell(row=summary_row_idx, column=c, value=val)
            if val is not None:
                cell.number_format = NUMBER_FORMAT
        summary_row_idx += 1

    _autosize(summary_ws, summary_headers)

    wb.save(output_path)
