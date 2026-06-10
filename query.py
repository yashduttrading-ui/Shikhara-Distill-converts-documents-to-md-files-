#!/usr/bin/env python3
"""
MD Vault - Smart Section Extractor

Instead of pasting an entire converted .md file (which can be 15k-25k tokens),
this scans the markdown for the sections most relevant to your question and
prints only those - typically cutting token usage by 5-20x.

Usage:
    python3 query.py <file.md or filename stem> "your question" [--top N]

Examples:
    python3 query.py "Tesla 2023 Annual Report" "what was revenue and net income?"
    python3 query.py tesla_2023 "cash flow from operations" --top 2

If you give just a stem/partial name, it searches markdown/ for a match.
"""

import re
import sys
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent
MD_DIR   = BASE_DIR / "markdown"

# Finance-domain synonym groups. If the question mentions any term in a group,
# all terms in that group count as matches in the document.
SYNONYMS = [
    {"revenue", "sales", "turnover", "total income", "net sales"},
    {"profit", "net income", "earnings", "net profit", "profit after tax", "pat"},
    {"loss", "net loss"},
    {"ebitda", "operating profit", "operating income"},
    {"cash flow", "cash flows", "operating activities", "investing activities", "financing activities"},
    {"balance sheet", "assets", "liabilities", "equity"},
    {"debt", "borrowings", "loans"},
    {"eps", "earnings per share"},
    {"dividend", "dividends"},
    {"expenses", "expenditure", "cost of goods sold", "cogs"},
    {"margin", "gross margin", "operating margin", "net margin"},
    {"growth", "increase", "decrease", "change", "yoy", "year over year"},
]

STOPWORDS = {
    "the", "a", "an", "is", "was", "were", "are", "of", "in", "on", "for",
    "to", "and", "or", "what", "which", "how", "much", "did", "do", "does",
    "their", "its", "this", "that", "with", "from", "as", "at", "by", "be",
    "give", "me", "show", "tell", "about", "find", "section",
}


def find_file(name: str) -> Path:
    p = Path(name)
    if p.suffix == ".md" and p.exists():
        return p
    if (MD_DIR / name).exists():
        return MD_DIR / name
    if (MD_DIR / f"{name}.md").exists():
        return MD_DIR / f"{name}.md"

    # fuzzy: case-insensitive substring match against markdown/*.md
    candidates = [f for f in MD_DIR.glob("*.md") if name.lower() in f.stem.lower()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        print("Multiple matches found, be more specific:")
        for c in candidates:
            print(f"  - {c.name}")
        sys.exit(1)

    print(f"No markdown file found for '{name}' in {MD_DIR}")
    sys.exit(1)


def expand_query_terms(question: str) -> set:
    q = question.lower()
    terms = set(re.findall(r"[a-z]+", q)) - STOPWORDS

    expanded = set(terms)
    for group in SYNONYMS:
        if any(term in q for term in group):
            for syn in group:
                expanded.update(re.findall(r"[a-z]+", syn))
    return expanded - STOPWORDS


def split_sections(text: str):
    """
    Split markdown into sections at heading lines (#, ##, ###, ...).
    Returns list of (heading, body_text) tuples. Leading content before the
    first heading becomes a section with heading "(intro)".
    """
    lines = text.split("\n")
    sections = []
    current_heading = "(intro)"
    current_body = []

    heading_re = re.compile(r"^(#{1,6})\s+(.*)")

    for line in lines:
        m = heading_re.match(line)
        if m:
            if current_body:
                sections.append((current_heading, "\n".join(current_body)))
            current_heading = m.group(2).strip()
            current_body = [line]
        else:
            current_body.append(line)

    if current_body:
        sections.append((current_heading, "\n".join(current_body)))

    return sections


def score_section(heading: str, body: str, query_terms: set) -> float:
    # The auto-generated table of contents isn't real content - never select it.
    if heading.strip().lower() == "detected sections":
        return float("-inf")

    text_lower = (heading + "\n" + body).lower()
    words = re.findall(r"[a-z]+", text_lower)
    word_count = max(len(words), 1)

    hits = sum(words.count(term) for term in query_terms)

    # Bonus if a query term appears in the heading itself
    heading_words = set(re.findall(r"[a-z]+", heading.lower()))
    heading_bonus = 3 * len(heading_words & query_terms)

    # Normalize hits by section length so giant "Page N" dumps don't dominate
    # purely by volume, but keep raw hits as the primary signal.
    return hits + heading_bonus - 0.0005 * word_count


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def main():
    parser = argparse.ArgumentParser(description="Extract the most relevant sections from a converted markdown file.")
    parser.add_argument("file", help="Markdown filename (or stem) in markdown/, or a full path")
    parser.add_argument("question", help="Your question, in quotes")
    parser.add_argument("--top", type=int, default=3, help="Number of top sections to return (default 3)")
    args = parser.parse_args()

    md_path = find_file(args.file)
    text = md_path.read_text(encoding="utf-8")

    query_terms = expand_query_terms(args.question)
    if not query_terms:
        print("Could not extract any keywords from the question.")
        sys.exit(1)

    sections = split_sections(text)
    scored = [
        (score_section(h, b, query_terms), h, b)
        for h, b in sections
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    top = [s for s in scored if s[0] > 0][: args.top]
    if not top:
        # fall back to the whole document if nothing scored
        top = scored[: args.top]

    output_parts = []
    for score, heading, body in top:
        output_parts.append(body.strip())

    output = "\n\n---\n\n".join(output_parts)

    full_tokens = estimate_tokens(text)
    out_tokens = estimate_tokens(output)

    print(output)
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"Source: {md_path.name}", file=sys.stderr)
    print(f"Full document: ~{full_tokens} tokens | Extracted: ~{out_tokens} tokens "
          f"({out_tokens / full_tokens:.0%})", file=sys.stderr)
    print("Sections used:", file=sys.stderr)
    for score, heading, _ in top:
        print(f"  - {heading}  (score {score:.1f})", file=sys.stderr)


if __name__ == "__main__":
    main()
