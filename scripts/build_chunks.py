"""Split extracted CFA curriculum text into searchable chunks.

Input:  data/raw/<topic>.txt  (from scripts/pdf2txt.swift, pages marked "=== PAGE n ===")
Output: data/chunks/<topic>.json  and  data/chunks/index.json

Each topic file holds the module outline (titles, LOS, lessons) and a list of
chunks tagged with module, lesson, kind (text/example/question/summary) and the
printed page range, so the app can cite "LM 9, p. 203".
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "chunks"

TOPIC_NAMES = {
    "quantitative_methods": "Quantitative Methods",
    "economics": "Economics",
    "corporate_finance": "Corporate Finance",
    "financial_statement_analysis": "Financial Statement Analysis",
    "equities": "Equity Investments",
    "fixed_income": "Fixed Income",
    "derivatives": "Derivatives",
    "alternative_investments": "Alternative Investments",
    "portfolio_construction": "Portfolio Management",
    "ethical_and_professional_standards": "Ethical and Professional Standards",
}

PAGE_RE = re.compile(r"^=== PAGE (\d+) ===$")
COPYRIGHT = "© CFA Institute. For candidate use only. Not for distribution."
MODULE_MARK = "L E A R N I N G M O D U L E"
RUNNING_HEADER_RE = re.compile(r"^(Learning Module \d+ .+|.+ \d{1,4})$")
HEADING_RE = re.compile(r"^[A-Z0-9][A-Z0-9 ,:;’'()/&–—.-]{3,}$")
LOS_VERBS = (
    "define describe explain calculate interpret compare contrast identify distinguish "
    "evaluate demonstrate discuss determine formulate analyze estimate construct recommend "
    "justify classify list state apply compute critique judge select summarize recognize "
    "understand assess outline"
).split()

QUESTION_HEADS = ("PRE-TEST", "LEARNING MODULE SELF-ASSESSMENT",
                  "QUESTION SET", "PRACTICE PROBLEMS", "SOLUTIONS")
# question blocks that are pure question lists (a TOC title inside them is an answer option, not a heading)
LIST_BLOCKS = ("PRE-TEST", "LEARNING MODULE SELF-ASSESSMENT", "QUESTION SET", "PRACTICE PROBLEMS", "SOLUTIONS")
CHUNK_TARGET = 2000
CHUNK_MAX = 3200


def read_pages(path):
    """Yield (pdf_page, printed_page, body_lines) with headers/footers stripped."""
    pages, cur = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = PAGE_RE.match(line)
        if m:
            cur = {"pdf": int(m.group(1)), "lines": []}
            pages.append(cur)
        elif cur is not None:
            cur["lines"].append(line.rstrip())
    last = None
    for p in pages:
        lines = [l for l in p["lines"][:3] if l.strip() != COPYRIGHT] + p["lines"][3:]
        printed = None
        if lines and lines[0].strip().isdigit():
            # even page: "150" then "Learning Module 6 ..." running header
            printed = int(lines[0])
            lines = lines[1:]
            if lines and lines[0].startswith("Learning Module "):
                lines = lines[1:]
        elif lines and RUNNING_HEADER_RE.match(lines[0]) and len(lines[0]) < 120:
            # odd page: "Lesson title 151"; only trust it when the number follows on
            tail = lines[0].rsplit(" ", 1)
            if len(tail) == 2 and tail[1].isdigit() and last is not None and int(tail[1]) in (last + 1, last + 2):
                printed = int(tail[1])
                lines = lines[1:]
        if printed is not None:
            last = printed
        yield p["pdf"], printed, lines


def kind_for(heading):
    h = heading.upper()
    if h.startswith(QUESTION_HEADS):
        return "question"
    if h.startswith("SUMMARY"):
        return "summary"
    if h.startswith(("EXAMPLE", "CASE STUDY", "KNOWLEDGE CHECK")):
        return "example"
    return "text"


def parse_los(lines):
    items = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("Mastery") or "candidate should be able to" in s:
            continue
        first = re.split(r"[ ,]", s, maxsplit=1)[0].lower()
        if first in LOS_VERBS or not items:
            items.append(s)
        else:
            items[-1] += " " + s
    return items


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def parse_toc(pages):
    """Read the front-matter table of contents: {module_n: [entry titles in order]}."""
    toc, cur, carry = {}, None, ""
    for _, _, lines in pages:
        if MODULE_MARK in (l.strip() for l in lines):
            break
        for raw in lines:
            line = (carry + " " + raw.strip()).strip() if carry else raw.strip()
            m = re.match(r"^Learning Module (\d+) (.+?)(?: (\d{1,4}))?$", line)
            if m:
                if m.group(3) is None:  # wrapped module title, page number on next line
                    carry = line
                    continue
                cur = int(m.group(1))
                toc[cur] = []
                carry = ""
                continue
            carry = ""
            m = re.match(r"^(.+?) (\d{1,4})$", line)
            if cur is not None and m and not m.group(1).startswith(("Practice Problems", "Solutions")):
                toc[cur].append(m.group(1))
    return toc


def build_topic(slug):
    pages = list(read_pages(RAW / f"{slug}.txt"))
    toc = parse_toc(pages)
    modules, chunks = [], []
    module = lesson = section = None
    kind = "text"
    buf, buf_pages = [], []
    los_mode, los_lines = False, []
    pending_mod = None  # collecting "L E A R N I N G M O D U L E / n / title..." lines
    toc_norm = {}  # normalized TOC title -> original, for the current module
    heading_open = None  # [heading text] while the next caps line may continue it

    def flush():
        nonlocal buf, buf_pages
        text = "\n".join(buf).strip()
        if module is not None and len(text) > 80:
            printed = [p for p in buf_pages if p is not None]
            chunks.append({
                "id": f"{slug}-{module['n']}-{len(chunks)}",
                "module": module["n"],
                "lesson": lesson,
                "section": section.title() if section and section.isupper() else section,
                "kind": kind,
                "page_start": min(printed) if printed else None,
                "page_end": max(printed) if printed else None,
                "text": text,
            })
        buf, buf_pages = [], []

    def toc_match(line):
        """TOC title that this body line starts (caps lesson heading or exact sub-heading)."""
        n = norm(line)
        if len(n) < 4:
            return None
        if n in toc_norm:
            return toc_norm[n]
        if line.isupper():
            for k, v in toc_norm.items():
                if k.startswith(n) and len(n) >= 10:
                    return v
        return None

    last_printed = None
    for pdf_page, printed, lines in pages:
        if printed is None and last_printed is not None:
            printed = last_printed + 1
        last_printed = printed if printed is not None else last_printed
        for raw in lines:
            line = raw.strip()
            if line == MODULE_MARK:
                flush()
                pending_mod = []
                continue
            if pending_mod is not None:
                if line.startswith("LEARNING OUTCOME"):
                    n = int(pending_mod[0]) if pending_mod and pending_mod[0].isdigit() else len(modules) + 1
                    title = re.sub(r"\s+by [A-Z].*$", "", " ".join(pending_mod[1:]).strip())  # drop author byline
                    module = {"n": n, "title": title, "los": [], "lessons": []}
                    modules.append(module)
                    toc_norm.clear()
                    toc_norm.update({norm(t): t for t in toc.get(n, [])})
                    lesson, section, kind, pending_mod = "Learning Outcomes", None, "text", None
                    los_mode, los_lines = True, []
                else:
                    pending_mod.append(line)
                continue
            if HEADING_RE.match(line) and not line.isdigit() and len(line) < 90 and line.isupper():
                if los_mode:
                    module["los"] = parse_los(los_lines)
                    los_mode = False
                if heading_open:
                    # second line of a wrapped heading ("INTRODUCTION: X" / "AND Y")
                    heading_open[0] = f"{heading_open[0]} {line}"
                    if kind != "text":
                        section = heading_open[0]
                    elif norm(lesson) != norm(heading_open[0]):
                        lesson = toc_match(heading_open[0]) or heading_open[0].title()
                    continue
                marker = kind_for(line)
                hit = toc_match(line)
                if marker != "text":
                    # practice/knowledge-check/example block inside the current lesson
                    flush()
                    kind = marker
                    section = line
                    heading_open = [line]
                    continue
                if hit or line.startswith(("INTRODUCTION", "LEARNING MODULE OVERVIEW")):
                    flush()
                    lesson, section, kind = hit or line.title(), None, "text"
                    if hit and hit not in module["lessons"]:
                        module["lessons"].append(hit)
                    heading_open = [line]
                    continue
                # other all-caps lines (table cells, exhibit labels) stay as body text
            elif (module is not None and not los_mode and line in toc_norm.values()
                  and not (kind == "question" and section and section.upper().startswith(LIST_BLOCKS))):
                flush()
                section, kind = line, "text"  # mixed-case TOC sub-heading ends any worked-example block
                continue
            if los_mode:
                los_lines.append(line)
                continue
            heading_open = None
            buf.append(raw)
            buf_pages.append(printed)
            size = sum(len(x) for x in buf)
            # split long lessons at paragraph-ish boundaries (sentence end) near the target size
            if size >= CHUNK_MAX or (size >= CHUNK_TARGET and line.endswith((".", ":", "?"))):
                flush()
    flush()
    return {"topic": slug, "name": TOPIC_NAMES.get(slug, slug), "modules": modules, "chunks": chunks}


def main(slugs):
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for slug in slugs:
        data = build_topic(slug)
        (OUT / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        kinds = {}
        for c in data["chunks"]:
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        index.append({
            "topic": slug, "name": data["name"],
            "modules": [{"n": m["n"], "title": m["title"], "los": m["los"], "lessons": m["lessons"]}
                        for m in data["modules"]],
            "chunk_count": len(data["chunks"]), "kinds": kinds,
        })
        print(f"{slug}: {len(data['modules'])} modules, {len(data['chunks'])} chunks {kinds}")
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:] or [p.stem for p in sorted(RAW.glob("*.txt"))])
