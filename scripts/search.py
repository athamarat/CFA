"""BM25 keyword search over data/chunks/*.json.

Usage: python3 -I scripts/search.py "put-call parity arbitrage" [--topic derivatives] [-k 5]
The app will use the same scoring in the browser; this script is for checking results.
"""
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

CHUNKS = Path(__file__).resolve().parent.parent / "data" / "chunks"
STOP = set("the a an of and or to in for on with by is are be as at that this from it its which".split())


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", text.lower().replace("–", "-")) if t not in STOP]


def load(topic=None):
    files = [CHUNKS / f"{topic}.json"] if topic else sorted(CHUNKS.glob("*.json"))
    docs = []
    for f in files:
        if f.name == "index.json":
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        titles = {m["n"]: m["title"] for m in data["modules"]}
        for c in data["chunks"]:
            c["topic"], c["module_title"] = data["name"], titles.get(c["module"], "")
            head = f"{c['module_title']} {c['lesson'] or ''} {c['section'] or ''}"
            c["_tf"] = Counter(tokens(c["text"]) + tokens(head) * 2)  # headings count double
            c["_len"] = sum(c["_tf"].values())
            docs.append(c)
    return docs


def search(docs, query, k=5, k1=1.2, b=0.75):
    q = tokens(query)
    n = len(docs)
    avg = sum(d["_len"] for d in docs) / n
    df = Counter(t for d in docs for t in set(q) if t in d["_tf"])
    scored = []
    for d in docs:
        s = 0.0
        for t in q:
            f = d["_tf"].get(t)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * d["_len"] / avg))
        if s:
            scored.append((s, d))
    return sorted(scored, key=lambda x: -x[0])[:k]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--topic")
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()
    for s, d in search(load(a.topic), a.query, a.k):
        pages = f"p.{d['page_start']}" + (f"-{d['page_end']}" if d["page_end"] != d["page_start"] else "")
        print(f"{s:6.2f}  {d['topic']} | LM{d['module']} {d['module_title'][:40]} | {d['lesson']} | "
              f"{d['section'] or '-'} | {d['kind']} | {pages}")
