# MD Vault

Drop a PDF/DOCX/XLSX/CSV into `watched/`, get a clean `.md` in `markdown/`
within ~2 seconds — plus a folder of small per-section files you can pick
from and upload directly to whatever AI you're using.

## Setup

```bash
pip install -r requirements.txt
chmod +x start.sh converter.py query.py
```

OCR (for scanned PDFs) requires the Tesseract OCR engine, installed via Homebrew:

```bash
brew install tesseract
```

If `tesseract` isn't installed, the converter still works fine for normal
(text-based) PDFs/DOCX/XLSX/CSV — it just skips OCR.

## Daily use

```bash
# Start the watcher (runs in background)
./start.sh start
./start.sh status
./start.sh stop

# Drop files
cp ~/Downloads/some_report.pdf watched/
```

That's it. Within a couple seconds you'll have:

```
markdown/
  report.pdf.md              <- combined file with everything
  report.pdf/                <- per-section files
    01_overview.md
    02_balance_sheet.md
    03_income_statement.md
    04_cash_flow_statement.md
    ...
```

Open the `report.pdf/` subfolder, skim the filenames, and drag the one or
two files you actually need straight into your AI chat (Claude, ChatGPT,
etc.). Each file is small, self-contained, and uses far fewer tokens than
uploading the whole document.

Output files are named `<original filename>.md` (e.g. `report.pdf.md`,
`report.xlsx.md`), so a PDF and a spreadsheet with the same name don't
overwrite each other.

## How conversion works

- **PDF**: page-by-page text + tables via pdfplumber. Headings are detected
  generically by font size/boldness (anything noticeably bigger or bolder
  than the body text) and tagged, then listed in a "Detected Sections" table
  of contents at the top of the file. Works on any PDF, not just financial
  reports.
- **Scanned/image-only pages**: if a page has no text layer, it's run through
  Tesseract OCR automatically and marked `*(text extracted via OCR)*`. The
  document header notes which page numbers were OCR'd. Heading detection
  doesn't apply to OCR'd pages (no font info available), so they won't appear
  in "Detected Sections".
- **DOCX**: headings, bold/italic, lists, and tables preserved. Heading
  1/2, Title, and Subtitle styles become file-split points.
- **XLSX/XLS**: each sheet becomes its own `## Sheet: <name>` section/table.
- **CSV/TSV**: single markdown table.

Any document with 2+ major sections also gets split into per-section files.
Tiny/misdetected sections (under ~150 characters) are merged into the
previous section so you don't end up with a folder full of one-line files.

## Optional: smart section extractor (`distill`)

If you'd rather just ask a question and get the relevant section
automatically (instead of browsing the per-section folder yourself), there's
an optional `query.py` script with a `distill` shortcut.

Add these to your `~/.bash_profile`:

```bash
# MD Vault: ask a question about a converted document, copy result to clipboard
distill() {
    python3 ~/MD_Vault/query.py "$@" | pbcopy
    echo "Copied to clipboard - paste into Claude with Cmd+V"
}

# MD Vault: list converted documents
distill-list() {
    ls ~/MD_Vault/markdown/ | grep -v gitkeep
}

# MD Vault: list saved sections (for uploading to Claude Projects)
distill-saved() {
    ls ~/MD_Vault/saved/ | grep -v gitkeep
}
```

Then:

```bash
distill-list                                    # see what's been converted
distill "some_report" "what was revenue?"       # extracts + copies to clipboard
```
Then `Cmd+V` to paste the result into Claude.

`query.py` splits the markdown on headings, expands your question with
finance synonyms (e.g. "revenue" also matches "sales"/"turnover"/"total
income"), scores each section by keyword overlap (with a bonus for matches
in the heading itself), and returns the top N (default 3) sections.

### Saving a section permanently (`--save`)

If you find yourself asking about the same section repeatedly (e.g. a
company's income statement), save it to its own small file with `--save`:

```bash
python3 query.py tesla_2023 "income statement" --save tesla_income_statement
# or with the shortcut:
distill tesla_2023 "income statement" --save tesla_income_statement
```

This writes the extracted section to `saved/tesla_income_statement.md` — a
small, standalone file you can upload to a Claude Project's knowledge base
for permanent, zero-token-per-message access. Run `distill-saved` to see
what you've saved.

## Notes

- For Claude Projects: upload your most-used `.md` files to a Project's
  knowledge base for zero-token-per-message access, and just refer to the
  document by name in chat.
- Logs: `converter.log`. PID file: `converter.pid`.
