# SEC EDGAR Financials Puller (Phase 1: Structured Financials)

Pulls standardized US-GAAP financials (Revenue, Cost of Revenue, COGS,
OpEx, R&D, SG&A, Net Income) for a list of tickers from SEC EDGAR's free
XBRL APIs (`data.sec.gov`) and writes them to an Excel workbook — one tab
per ticker, plus a Summary tab with the latest period for every ticker.

No API key required. SEC does require a descriptive `User-Agent` header
(your name + email) on every request, and asks that you keep request
volume to roughly 10/sec or fewer — this tool handles both automatically.

## Setup

1. Create a virtualenv and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Tell SEC who you are.** Open `config.py` and replace the placeholder
   with your real name and email:

   ```python
   USER_AGENT = "Your Name your.email@example.com"
   ```

   This is the one thing you need to edit before running the tool. If you'd
   rather not put it in a file, you can instead set the
   `SEC_EDGAR_USER_AGENT` environment variable, or pass `--user-agent` on
   the command line — either overrides `config.py`.

## Usage

```bash
python pull_financials.py --tickers DDOG,BILL,SMAR --output financials.xlsx
```

Limit how far back to pull (keeps the N most recent fiscal periods per
ticker, mixing quarters and years as reported):

```bash
python pull_financials.py --tickers DDOG,BILL,SMAR --output financials.xlsx --quarters 8
```

Other flags:

- `--cache-dir DIR` — where cached SEC responses are stored (default `./cache`).
- `--refresh` — ignore the cache and re-download everything.
- `-v` / `--verbose` — debug logging.

Run `python pull_financials.py --help` for the full list.

## What it does

1. Downloads and caches SEC's `company_tickers.json` to map ticker → CIK.
2. For each ticker, fetches
   `https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digit-padded}.json`
   (cached to `cache/CIK##########.json` so re-runs don't re-hit SEC).
3. Extracts these concepts, trying a short list of fallback US-GAAP tags
   per concept (companies tag economically-equivalent line items
   differently — e.g. `Revenues` vs.
   `RevenueFromContractWithCustomerExcludingAssessedTax`). See
   `CONCEPT_MAP` in `financials.py` if you want to add more fallback tags
   for a ticker's specific taxonomy quirks:
   - Revenue
   - Cost of Revenue
   - Cost of Goods & Services Sold
   - Operating Expenses
   - R&D Expense
   - SG&A Expense
   - Net Income (Loss)
4. Keeps only facts sourced from `10-K` and `10-Q` filings (ignores other
   form types, and amendments). When a fact for the same fiscal period was
   reported more than once (e.g. restated as a prior-period comparative in
   a later filing), the earliest-filed value is kept.
5. Writes one Excel tab per ticker (rows = fiscal periods, sorted oldest
   to newest) plus a `Summary` tab showing the most recent period for
   every ticker side by side.

## Error handling

Tickers that can't be resolved to a CIK, have no XBRL data, or fail to
parse are skipped with a warning on the console — the run continues for
the remaining tickers, and the ticker still gets a row in the Summary tab
noting why it has no data (e.g. "No CIK match", "No XBRL data available").

## Notes / limitations (Phase 1 scope)

- Quarter-only figures (e.g. a standalone Q4) aren't synthesized by
  subtracting 9-month YTD from full-year — the tool only reports what SEC
  provides directly (per the `fy`/`fp`/`start`/`end` fields).
- `--quarters N` truncates by *number of periods returned*, not
  strictly by calendar quarters — a company where SEC has only annual
  (10-K) periods and no interim (10-Q) history will show fiscal years
  under that flag.
- This is Phase 1 (structured financials only). Net dollar retention and
  other qualitative/MD&A-derived metrics are a planned Phase 2, not built
  yet.

## Project layout

- `pull_financials.py` — CLI entry point / orchestration.
- `sec_client.py` — rate-limited, caching HTTP client for SEC endpoints.
- `financials.py` — concept fallback map and per-period extraction logic.
- `excel_writer.py` — builds the output workbook.
- `config.py` — your `USER_AGENT` setting.
