# MD Vault

Drop a PDF/DOCX/XLSX/CSV into `watched/`, get a clean `.md` in `markdown/`
within ~2 seconds — plus a folder of small per-company files you can pick
from and upload directly to whatever AI you're using.

It's built for recurring report-style documents that cover many companies
in one file — sell-side research notes, conference/management-meeting
takeaways, sector roundups, etc. — and automatically splits them into one
file per company, with cover pages, intros, and disclosure/disclaimer
boilerplate stripped out. Any other document (financial statements,
contracts, plain reports) still gets converted and split by section as
before.

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
  conference_takeaways.pdf.md       <- combined file with everything
  conference_takeaways.pdf/         <- one file per company
    01_cartrade_tech.md
    02_au_small_finance_bank_ltd_aubank_in.md
    03_bank_of_baroda_bob_in.md
    ...
```

Open the `conference_takeaways.pdf/` subfolder, skim the filenames, and drag
the one or two files you actually need straight into your AI chat (Claude,
ChatGPT, etc.). Each file is small, self-contained, and uses far fewer
tokens than uploading the whole document.

Output files are named `<original filename>.md` (e.g. `report.pdf.md`,
`report.xlsx.md`), so a PDF and a spreadsheet with the same name don't
overwrite each other.

## How conversion works

- **PDF**: page-by-page text + tables via pdfplumber. Headings are detected
  generically by font size/boldness (anything noticeably bigger or bolder
  than the body text) and tagged, then listed in a "Detected Sections" table
  of contents at the top of the file.
- **Scanned/image-only pages**: if a page has no text layer, it's run through
  Tesseract OCR automatically and marked `*(text extracted via OCR)*`. The
  document header notes which page numbers were OCR'd. Heading detection
  doesn't apply to OCR'd pages (no font info available), so they won't appear
  in "Detected Sections".
- **DOCX**: headings, bold/italic, lists, and tables preserved. Heading
  1/2, Title, and Subtitle styles become file-split points.
- **XLSX/XLS**: each sheet becomes its own `## Sheet: <name>` section/table.
- **CSV/TSV**: single markdown table.

## How per-company splitting works

For PDFs, after the generic heading pass above, a second pass looks for the
common sell-side rating-note pattern: a company name on its own line,
immediately followed by a rating line like `ADD | CMP: Rs 1,772 | TP: Rs
2,150` or `NOT COVERED | CMP: Rs 520`. Each match becomes a file-split point,
even if the company name wasn't picked up as a "big" heading on its own.

When the document is split into per-section/per-company files, a few
cleanup passes run automatically:

- **Cover pages and intros dropped**: the text before the first detected
  heading, plus headings that look like cover-page banners (e.g. "Day 1 Key
  Takeaways", "Conference Takeaways"), are dropped entirely.
- **Boilerplate cut off**: once a heading like "Disclosures", "Disclaimers",
  "Glossary", "Ratings & Definitions", "Stocks Mentioned", or "Research
  Analyst" certifications is reached, everything from there to the end of the
  document is dropped. This also catches that boilerplate when it shows up
  *inside* the last company's section (e.g. a ratings table or a
  Bloomberg/BofA "Stocks Mentioned" ticker table tacked onto the last
  write-up) and trims it from there.
- **Non-company sections dropped**: if the document tags company headings
  with a ticker (e.g. "AU Small Finance Bank Ltd (AUBANK IN)"), any section
  *without* a ticker — panel/topic write-ups, sector "Takeaways" headers,
  etc. — is dropped, leaving only the per-company files.
- **Tiny sections merged**: sections under ~150 characters (likely
  misdetected headings — page numbers, logos, stray words) are merged into
  the previous section instead of getting their own file.

If fewer than 2 sections remain after all of this, no per-section folder is
created — you just get the combined `.md` file.

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
