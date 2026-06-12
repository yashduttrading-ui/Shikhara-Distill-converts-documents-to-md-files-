#!/usr/bin/env python3
"""
MD Vault - Auto Markdown Converter
Watches ~/MD_Vault/watched and converts PDF, DOCX, XLSX/XLS, CSV/TSV to clean
Markdown in ~/MD_Vault/markdown.

For PDFs that look like financial reports, it also detects common statement
headings (Balance Sheet, Income Statement, Cash Flow Statement, Notes, etc.)
and inserts a table of contents + clear section markers so a downstream tool
(query.py) can pull out just the relevant section.

Pages with no extractable text layer (scanned pages) are run through
Tesseract OCR automatically.

Zero cost. Runs locally.
"""

import re
import sys
import time
import shutil
import logging
from pathlib import Path
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import pdfplumber
from docx import Document
import openpyxl
import pandas as pd

try:
    import pytesseract
    import pypdfium2 as pdfium

    # Homebrew's tesseract isn't always on PATH for background processes,
    # so point pytesseract at the common Homebrew install locations directly.
    if shutil.which("tesseract") is None:
        for candidate in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
            if Path(candidate).exists():
                pytesseract.pytesseract.tesseract_cmd = candidate
                break

    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
WATCH_DIR = BASE_DIR / "watched"
OUT_DIR   = BASE_DIR / "markdown"
LOG_FILE  = BASE_DIR / "converter.log"

WATCH_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

SUPPORTED = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".tsv"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("md_vault")


# ═══════════════════════════════════════════════════════════════════════════════
# GENERIC HEADING DETECTION (font-size / bold based)
# ═══════════════════════════════════════════════════════════════════════════════

MAX_HEADING_WORDS = 12
MAX_HEADING_CHARS = 90


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()


def _detect_headings(pdf) -> tuple[dict, float]:
    """
    Scans every page's words (with font size/weight info) and figures out
    which lines are headings - i.e. noticeably larger than the page's most
    common (body) font size, or bold and short.

    Returns:
        headings_by_page: {page_index (1-based): [(normalized_text, original_text, level), ...]}
        body_size: the most common font size across the document
    """
    size_counts: dict[int, int] = {}
    page_words = []

    for page in pdf.pages:
        words = page.extract_words(extra_attrs=["size", "fontname"])
        page_words.append(words)
        for w in words:
            size = round(w["size"])
            size_counts[size] = size_counts.get(size, 0) + 1

    body_size = max(size_counts, key=size_counts.get) if size_counts else 10

    headings_by_page: dict[int, list] = {}

    for page_idx, words in enumerate(page_words, 1):
        # Group words into lines by their vertical position
        lines: dict[int, list] = {}
        for w in words:
            top = round(w["top"])
            lines.setdefault(top, []).append(w)

        page_headings = []
        for top in sorted(lines):
            line_words = sorted(lines[top], key=lambda w: w["x0"])
            text = " ".join(w["text"] for w in line_words).strip()
            if not text or len(text) > MAX_HEADING_CHARS or len(line_words) > MAX_HEADING_WORDS:
                continue

            avg_size = sum(w["size"] for w in line_words) / len(line_words)
            is_bold = any("bold" in w["fontname"].lower() for w in line_words)

            if avg_size > body_size * 1.4:
                level = 2  # big title -> ##
            elif avg_size > body_size * 1.15 or is_bold:
                level = 3  # slightly bigger or bold -> ###
            else:
                continue

            page_headings.append((_normalize(text), text, level))

        if page_headings:
            headings_by_page[page_idx] = page_headings

    return headings_by_page, body_size


# ═══════════════════════════════════════════════════════════════════════════════
# OCR FALLBACK (for scanned pages with no text layer)
# ═══════════════════════════════════════════════════════════════════════════════

OCR_DPI = 200


def _ocr_page(pdfium_doc, page_index: int) -> str:
    """Renders a page to an image and runs Tesseract OCR on it."""
    page = pdfium_doc[page_index]
    bitmap = page.render(scale=OCR_DPI / 72)
    image = bitmap.to_pil()
    return pytesseract.image_to_string(image).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERTERS
# ═══════════════════════════════════════════════════════════════════════════════

def pdf_to_md(path: Path) -> str:
    """
    Extracts text + tables from a PDF using pdfplumber, page by page.
    Detects headings generically (anything noticeably larger or bolder than
    body text) and tags them with `<!-- SECTION: ... -->` markers so
    query.py can find them, plus builds a table of contents at the top.
    """
    body_lines = []
    sections_found = []  # list of (heading_text, page_number, level)
    ocr_pages = []  # page numbers that were OCR'd
    pdfium_doc = None

    with pdfplumber.open(path) as pdf:
        headings_by_page, _ = _detect_headings(pdf)

        for i, page in enumerate(pdf.pages, 1):
            page_lines = [f"\n## Page {i}\n"]

            # Tables first (highest fidelity)
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    if not table or not table[0]:
                        continue
                    header  = table[0]
                    rows    = table[1:]
                    md_header = "| " + " | ".join(str(c or "").strip() for c in header) + " |"
                    md_sep    = "| " + " | ".join(["---"] * len(header)) + " |"
                    md_rows   = [
                        "| " + " | ".join(str(c or "").strip() for c in row) + " |"
                        for row in rows
                    ]
                    page_lines.append("\n" + "\n".join([md_header, md_sep] + md_rows) + "\n")

            # Body text
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""

            # No text layer (likely a scanned page) - fall back to OCR
            if not text.strip() and not tables and OCR_AVAILABLE:
                if pdfium_doc is None:
                    pdfium_doc = pdfium.PdfDocument(path)
                text = _ocr_page(pdfium_doc, i - 1)
                if text:
                    ocr_pages.append(i)
                    page_lines.append("*(text extracted via OCR)*\n")

            if text.strip():
                cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()

                page_headings = {h[0]: h for h in headings_by_page.get(i, [])}
                out_lines = []
                for raw_line in cleaned.split("\n"):
                    norm = _normalize(raw_line)
                    heading = page_headings.get(norm)
                    if heading:
                        _, original, level = heading
                        sections_found.append((original, i, level))
                        marker = "#" * level
                        # Only the biggest headings (level 2) become file-split
                        # points - level 3 (bold/slightly-larger) stays as a
                        # heading for query.py but doesn't fragment the output
                        # into too many small files.
                        if level == 2:
                            out_lines.append(f"\n<!-- SECTION: {original} -->\n{marker} {original}")
                        else:
                            out_lines.append(f"\n{marker} {original}")
                    else:
                        out_lines.append(raw_line)
                cleaned = "\n".join(out_lines)
                page_lines.append(cleaned + "\n")

            body_lines.append("\n".join(page_lines))

    if pdfium_doc is not None:
        pdfium_doc.close()

    # Header + optional table of contents
    header = [f"# {path.stem}\n", f"*Source: {path.name}*\n"]
    if ocr_pages:
        pages_str = ", ".join(str(p) for p in ocr_pages)
        header.append(f"*OCR was used for page(s): {pages_str}*\n")
    if sections_found:
        header.append("\n## Detected Sections\n")
        seen = set()
        for name, page_no, level in sections_found:
            key = (name, page_no)
            if key in seen:
                continue
            seen.add(key)
            indent = "  " * (level - 2)
            header.append(f"{indent}- {name} (page {page_no})")
        header.append("")
    header.append("\n---\n")

    return "\n".join(header) + "\n".join(body_lines)


def docx_to_md(path: Path) -> str:
    """
    Converts DOCX -> Markdown preserving headings, bold/italic, lists, tables.
    """
    doc = Document(path)
    md  = [f"# {path.stem}\n"]

    HEADING_MAP = {
        "heading 1": "#", "heading 2": "##", "heading 3": "###",
        "heading 4": "####", "heading 5": "#####", "title": "#",
        "subtitle": "##",
    }

    def para_to_md(para) -> str:
        style = para.style.name.lower()
        prefix = HEADING_MAP.get(style, "")

        inline = ""
        for run in para.runs:
            text = run.text
            if not text:
                continue
            if run.bold and run.italic:
                text = f"***{text}***"
            elif run.bold:
                text = f"**{text}**"
            elif run.italic:
                text = f"*{text}*"
            inline += text

        if not inline.strip():
            return ""

        if style.startswith("list bullet"):
            return f"- {inline}"
        if style.startswith("list number"):
            return f"1. {inline}"

        if prefix:
            # Major headings (Heading 1/2, Title, Subtitle) become file-split
            # points, mirroring the level-2 PDF headings.
            if style in ("heading 1", "heading 2", "title", "subtitle"):
                return f"\n<!-- SECTION: {inline} -->\n{prefix} {inline}"
            return f"{prefix} {inline}"
        return inline

    from docx.text.paragraph import Paragraph
    from docx.table import Table

    for block in doc.element.body:
        tag = block.tag.split("}")[-1]

        if tag == "p":
            para = Paragraph(block, doc)
            result = para_to_md(para)
            if result:
                md.append(result)
            else:
                md.append("")

        elif tag == "tbl":
            table = Table(block, doc)
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if rows:
                header = rows[0]
                md.append("\n| " + " | ".join(header) + " |")
                md.append("| " + " | ".join(["---"] * len(header)) + " |")
                for row in rows[1:]:
                    md.append("| " + " | ".join(row) + " |")
                md.append("")

    return "\n".join(md)


def xlsx_to_md(path: Path) -> str:
    """Converts all sheets in an Excel file to Markdown tables, one section per sheet."""
    md = [f"# {path.stem}\n"]

    try:
        xl = pd.ExcelFile(path)
        sheets = xl.sheet_names
    except Exception:
        wb = openpyxl.load_workbook(path, data_only=True)
        sheets = wb.sheetnames

    if len(sheets) > 1:
        md.append("\n## Sheets\n")
        for s in sheets:
            md.append(f"- {s}")
        md.append("")

    for sheet_name in sheets:
        md.append(f"\n## Sheet: {sheet_name}")
        md.append(f"<!-- SECTION: {sheet_name} -->\n")
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, header=0)
            df = df.fillna("").astype(str)

            header  = "| " + " | ".join(df.columns.astype(str)) + " |"
            sep     = "| " + " | ".join(["---"] * len(df.columns)) + " |"
            rows    = ["| " + " | ".join(row) + " |" for _, row in df.iterrows()]
            md.extend([header, sep] + rows)
        except Exception as e:
            md.append(f"*Could not parse sheet: {e}*")

    return "\n".join(md)


def csv_to_md(path: Path) -> str:
    """Converts CSV/TSV to a Markdown table."""
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        df = pd.read_csv(path, sep=sep)
        df = df.fillna("").astype(str)
        md = [f"# {path.stem}\n"]
        header  = "| " + " | ".join(df.columns.astype(str)) + " |"
        sep_row = "| " + " | ".join(["---"] * len(df.columns)) + " |"
        rows    = ["| " + " | ".join(row) + " |" for _, row in df.iterrows()]
        md.extend([header, sep_row] + rows)
        return "\n".join(md)
    except Exception as e:
        return f"# {path.stem}\n\n*Error parsing CSV: {e}*"


# ═══════════════════════════════════════════════════════════════════════════════
# COMPANY HEADING DETECTION (for sell-side research notes)
# ═══════════════════════════════════════════════════════════════════════════════

# Common Indian sell-side rating-note convention: each company's write-up
# starts with the company name on its own line, immediately followed by a
# rating line like "ADD | CMP: Rs 1,772 | TP: Rs 2,150" or
# "NOT COVERED | CMP: Rs 520".
COMPANY_RATING_RE = re.compile(
    r"^(BUY|ADD|REDUCE|SELL|HOLD|ACCUMULATE|NOT COVERED)\b.*\bCMP\b",
    re.IGNORECASE,
)


_HEADING_LINE_RE = re.compile(r"^#{1,6}\s*(.*)")


def _mark_company_headings(md_text: str) -> str:
    """
    Company names in rating notes are often only bold (not a noticeably
    bigger font), so the generic font-based heading detector misses them -
    or detects both the company name AND its rating line as level-3 (###)
    headings, neither of which becomes a file-split point on its own.
    This scans for rating lines (stripping any existing heading markers) and
    retroactively marks the line above as a `<!-- SECTION: ... -->` heading
    so split_into_sections() treats each company as a file-split point.
    """
    lines = md_text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        m = _HEADING_LINE_RE.match(stripped)
        content = m.group(1).strip() if m else stripped
        if not COMPANY_RATING_RE.match(content):
            continue

        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0:
            continue

        prev = lines[j].strip()
        if prev.startswith(("<!--", "|")):
            continue

        pm = _HEADING_LINE_RE.match(prev)
        name = pm.group(1).strip() if pm else prev
        if not name or len(name) > 80:
            continue

        lines[j] = f"\n<!-- SECTION: {name} -->\n## {name}"

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PER-SECTION FILE SPLITTING
# ═══════════════════════════════════════════════════════════════════════════════

def _slugify(text: str) -> str:
    """Turns a heading into a filesystem-safe slug, e.g. 'Cash Flow!' -> 'cash_flow'."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text or "section"


# Sections shorter than this (in characters) are usually misdetected
# headings (page numbers, logos, stray words) - merge them into the
# previous section instead of giving them their own file.
MIN_SECTION_CHARS = 150

# Headings matching these patterns are boilerplate that marks the end of the
# actual content (disclosures, glossaries, analyst certifications, etc.) -
# once one is seen, everything from there to the end of the document is
# dropped entirely.
STOP_HEADING_RE = re.compile(
    r"disclosure|disclaimer|glossary|stocks?\s+mentioned|research\s+analyst"
    r"|ratings?\s*&?\s*definitions|important\s+notice|certification",
    re.IGNORECASE,
)

# Headings matching these patterns are cover-page/title material (conference
# day titles, "Key Takeaways" banners, etc.) rather than real content about a
# company - drop just this one section, but keep going.
SKIP_HEADING_RE = re.compile(
    r"^day\s+\d+|key\s+takeaways|conference\s+takeaways|takeaways\s*$",
    re.IGNORECASE,
)

# Matches a markdown table header row whose first cell is a short ALL-CAPS
# label, e.g. "| RATINGS & DEFINITIONS |  |  |  |" or "| DISCLAIMERS |".
_TABLE_HEADER_RE = re.compile(r"^\|\s*([A-Z][A-Z\s&/]{2,40})\s*\|")

# A "Stocks Mentioned" appendix table often has no text heading at all - it's
# just a Bloomberg/BofA ticker table dropped onto the page. Detect it by its
# column headers instead.
_STOCKS_TABLE_RE = re.compile(r"bloomberg\s+ticker", re.IGNORECASE)

# Matches a ticker tag in a company heading, e.g. "(AUBANK IN)",
# "(POWF IN)", "(BLSTR IN, Not covered )". Used to tell company sections
# apart from non-company sections (panel/topic write-ups, sector "Takeaways"
# headers) in documents that tag each company heading with its ticker.
_TICKER_HEADING_RE = re.compile(r"\([A-Z0-9.&]{2,15}\s+IN\b[^)]*\)")


def _truncate_at_stop_heading(body: str) -> str:
    """
    Boilerplate like "RATINGS & DEFINITIONS" / "DISCLAIMERS" is often only a
    level-3 heading or a table header row, so it doesn't get its own
    `<!-- SECTION: ... -->` marker and ends up appended to the last real
    section instead. Scan line-by-line for a heading or table-header row
    matching STOP_HEADING_RE, or a "Stocks Mentioned"-style ticker table, and
    cut everything from there (and the table it belongs to) onward.
    """
    lines = body.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        m = _HEADING_LINE_RE.match(stripped)
        if m:
            text = m.group(1).strip()
        else:
            tm = _TABLE_HEADER_RE.match(stripped)
            text = tm.group(1).strip() if tm else None
        if text and STOP_HEADING_RE.search(text):
            return "\n".join(lines[:i]).strip()
        if _STOCKS_TABLE_RE.search(stripped):
            j = i
            while j > 0 and (lines[j - 1].strip().startswith("|") or not lines[j - 1].strip()):
                j -= 1
            return "\n".join(lines[:j]).strip()
    return body


def split_into_sections(md_text: str):
    """
    Splits converted markdown on `<!-- SECTION: name -->` markers into
    (name, content) pairs, for writing each section to its own file.

    The intro before the first marker (titles, analyst lists, etc.) is
    dropped. Headings matching SKIP_HEADING_RE (cover-page/title banners)
    are dropped too. Once a heading matches STOP_HEADING_RE (disclosures,
    glossary, etc.), that section and everything after it is dropped.

    Tiny remaining sections (likely misdetected headings) are merged into
    the previous section. Returns [] if fewer than 2 sections remain (not
    worth splitting).
    """
    marker_re = re.compile(r"<!-- SECTION: (.*?) -->")

    pieces = marker_re.split(md_text)
    # pieces alternates: [intro, name1, body1, name2, body2, ...]
    rest = pieces[1:]

    sections = []
    for i in range(0, len(rest) - 1, 2):
        name = rest[i].strip()
        body = rest[i + 1].strip()
        if not body:
            continue
        if STOP_HEADING_RE.search(name):
            break
        if SKIP_HEADING_RE.search(name):
            continue
        body = _truncate_at_stop_heading(body)
        if not body:
            continue
        sections.append((name, body))

    # If this document tags company headings with a ticker (e.g. "(AUBANK
    # IN)"), drop every section that *isn't* a company - panel/topic
    # write-ups and sector "Takeaways" headers don't carry a ticker.
    if any(_TICKER_HEADING_RE.search(name) for name, _ in sections):
        sections = [(name, body) for name, body in sections if _TICKER_HEADING_RE.search(name)]

    # Merge short sections into the previous one (or the next, if it's first)
    merged = []
    for name, body in sections:
        if len(body) < MIN_SECTION_CHARS and merged:
            prev_name, prev_body = merged[-1]
            merged[-1] = (prev_name, prev_body + "\n\n" + body)
        else:
            merged.append((name, body))

    # If the very first section ended up tiny (no previous to merge into),
    # fold it into the second one.
    while len(merged) >= 2 and len(merged[0][1]) < MIN_SECTION_CHARS:
        name0, body0 = merged.pop(0)
        name1, body1 = merged[0]
        merged[0] = (name1, body0 + "\n\n" + body1)

    if len(merged) < 2:
        return []

    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════════

def convert(src: Path) -> Path | None:
    ext = src.suffix.lower()
    if ext not in SUPPORTED:
        return None

    # Include the original extension in the output name (e.g. report.pdf.md)
    # so report.pdf and report.xlsx don't overwrite the same .md file.
    out_path = OUT_DIR / (src.name + ".md")
    log.info(f"Converting: {src.name} -> {out_path.name}")

    try:
        if ext == ".pdf":
            md_text = pdf_to_md(src)
            md_text = _mark_company_headings(md_text)
        elif ext in {".docx", ".doc"}:
            md_text = docx_to_md(src)
        elif ext in {".xlsx", ".xls"}:
            md_text = xlsx_to_md(src)
        elif ext in {".csv", ".tsv"}:
            md_text = csv_to_md(src)
        else:
            return None

        md_text += f"\n\n---\n*Converted by MD Vault on {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n"

        out_path.write_text(md_text, encoding="utf-8")
        log.info(f"Saved: {out_path}")

        # Also split into per-section files, e.g. markdown/report.pdf/01_intro.md,
        # so users who don't want the query/distill tooling can just browse and
        # upload whichever section files they need.
        sections = split_into_sections(md_text)
        if sections:
            section_dir = OUT_DIR / src.name
            if section_dir.exists():
                shutil.rmtree(section_dir)
            section_dir.mkdir(parents=True)
            for i, (name, body) in enumerate(sections, start=1):
                slug = _slugify(name)
                section_path = section_dir / f"{i:02d}_{slug}.md"
                section_path.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
            log.info(f"Split into {len(sections)} section files in {section_dir}")

        return out_path

    except Exception as e:
        log.error(f"Failed on {src.name}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# WATCHER
# ═══════════════════════════════════════════════════════════════════════════════

class VaultHandler(FileSystemEventHandler):
    def __init__(self):
        self._processing = set()

    def _handle(self, path: Path):
        if path.suffix.lower() in SUPPORTED and path not in self._processing:
            self._processing.add(path)
            time.sleep(1.5)  # let the write finish
            convert(path)
            self._processing.discard(path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(Path(event.dest_path))


def batch_convert_existing():
    existing = [f for f in WATCH_DIR.iterdir() if f.suffix.lower() in SUPPORTED]
    if existing:
        log.info(f"Found {len(existing)} existing file(s) to convert...")
        for f in existing:
            convert(f)


def main():
    log.info("=" * 60)
    log.info("  MD Vault - Auto Markdown Converter")
    log.info(f"  Watching : {WATCH_DIR}")
    log.info(f"  Output   : {OUT_DIR}")
    log.info("=" * 60)

    batch_convert_existing()

    handler  = VaultHandler()
    observer = Observer()
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()

    log.info("Watching for new files. Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        log.info("MD Vault stopped.")
    observer.join()


if __name__ == "__main__":
    main()
