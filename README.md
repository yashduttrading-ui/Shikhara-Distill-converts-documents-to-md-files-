# MD Vault

Drop a PDF/DOCX/XLSX/CSV into `watched/`, get a clean `.md` in `markdown/` within ~2 seconds.
Then ask a question and get only the relevant section instead of pasting the whole file.

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

# Ask a question — prints only the relevant section(s)
python3 query.py "some_report" "what was net income and revenue?"
python3 query.py "some_report" "cash flow from operations" --top 2
```

`query.py` accepts a partial filename (matches anything in `markdown/`) and
a question in quotes. It prints the most relevant section(s) to stdout and a
token-savings summary to stderr.

Output files are named `<original filename>.md` (e.g. `report.pdf.md`,
`report.xlsx.md`), so a PDF and a spreadsheet with the same name don't
overwrite each other.

### Shortcuts (`distill`)

If you've added the shell functions below to your `~/.bash_profile`:

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

then the daily workflow is just:

```bash
distill-list                                    # see what's been converted
distill "some_report" "what was revenue?"       # extracts + copies to clipboard
```
Then `Cmd+V` to paste the result into Claude.

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

## How conversion works

- **PDF**: page-by-page text + tables via pdfplumber. Headings are detected
  generically by font size/boldness (anything noticeably bigger or bolder
  than the body text) and tagged with `<!-- SECTION: ... -->`, then listed in
  a "Detected Sections" table of contents at the top of the file. Works on
  any PDF, not just financial reports.
- **Scanned/image-only pages**: if a page has no text layer, it's run through
  Tesseract OCR automatically and marked `*(text extracted via OCR)*`. The
  document header notes which page numbers were OCR'd. Heading detection
  doesn't apply to OCR'd pages (no font info available), so they won't appear
  in "Detected Sections".
- **DOCX**: headings, bold/italic, lists, and tables preserved.
- **XLSX/XLS**: each sheet becomes its own `## Sheet: <name>` section/table.
- **CSV/TSV**: single markdown table.

## How the section extractor works

`query.py` splits the markdown on headings (`#`, `##`, `###`, including
`## Page N` and `## Sheet: ...`), expands your question with finance synonyms
(e.g. "revenue" also matches "sales"/"turnover"/"total income"), scores each
section by keyword overlap (with a bonus for matches in the heading itself),
and returns the top N (default 3).

## Notes

- For Claude Projects: upload your most-used `.md` files to a Project's
  knowledge base for zero-token-per-message access, and just refer to the
  document by name in chat.
- Logs: `converter.log`. PID file: `converter.pid`.
