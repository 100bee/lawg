"""Fetch current statute text from law.go.kr into backend/data/sources/ (one article per file).

usage: python3 scripts/fetch_statutes.py
The text is copied verbatim from the official page; amendment notes like <개정 2025. 12. 23.> are dropped.
shortcut: scrapes the public article page; switch to the Open API (LAW_API_OC) once it is approved.
"""
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backend" / "data" / "sources"
BASE = "https://www.law.go.kr"

# (law name as law.go.kr resolves it, article, slug, categories)
ARTICLES = [
    ("형법", "제347조", "criminal-347", "fraud"),
    ("형법", "제347조의2", "criminal-347-2", "fraud,account"),
    ("형법", "제307조", "criminal-307", "defamation"),
    ("형법", "제310조", "criminal-310", "defamation"),
    ("형법", "제311조", "criminal-311", "insult"),
    ("형법", "제312조", "criminal-312", "insult,defamation"),
    ("정보통신망법", "제70조", "network-70", "defamation"),
    ("성폭력처벌법", "제13조", "sexual-violence-13", "obscenity"),
    ("정보통신망법", "제48조", "network-48", "account"),
    ("정보통신망법", "제49조", "network-49", "account"),
    ("정보통신망법", "제71조", "network-71", "account"),
    ("형법", "제283조", "criminal-283", "threat"),
    ("스토킹처벌법", "제2조", "stalking-2", "threat"),
    ("스토킹처벌법", "제18조", "stalking-18", "threat"),
    # left out 2026-11-12: 제44조의7 (불법정보 유통금지) is 2,657 chars of prohibitions; 제74조 already quotes the
    # punishable acts. Add back as ("정보통신망법", "제44조의7", "network-44-7", "obscenity,threat") if needed.
    ("정보통신망법", "제74조", "network-74", "obscenity,threat"),
    ("형법", "제52조", "criminal-52", "fraud,insult,defamation,obscenity,account,threat"),
]


def get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (lawg statute fetch)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def text_of(fragment: str) -> str:
    fragment = re.sub(r'<span class="sfon">.*?</span>', "", fragment, flags=re.S)  # amendment notes
    fragment = re.sub(r'<input[^>]*>', "", fragment)
    return re.sub(r"[ \t ]+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def fetch(law: str, article: str) -> dict:
    shortcut = f"{BASE}/{urllib.parse.quote(f'법령/{law}/{article}')}"
    frame = re.search(r'src="(/LSW/+lsSideInfoP\.do\?[^"]+)"', get(shortcut))
    if not frame:
        raise ValueError(f"{law} {article}: article page not found")
    page = get(BASE + html.unescape(frame.group(1)))
    names = [text_of(h) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", page, re.S)]
    law_name = re.sub(r"\s*\(\s*약칭:.*\)\s*$", "", next(n for n in names if n != "법령"))  # first h2 is site nav
    enforcement = re.search(r"\[시행 (\d{4})\. (\d{1,2})\. (\d{1,2})\.\] \[([^\]]+)\]", page)
    body = re.search(r'<div class="lawcon">(.*?)</div>', page, re.S)
    if not (enforcement and body):
        raise ValueError(f"{law} {article}: unexpected page layout")
    lines = [text_of(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body.group(1), re.S)]
    lines = [line for line in lines if line]
    heading = re.match(r"(제\d+조(?:의\d+)?)\(([^)]*)\)\s*", lines[0])
    if not heading or heading.group(1) != article:
        raise ValueError(f"{law} {article}: got {lines[0][:30]!r}")
    year, month, day, promulgation = enforcement.groups()
    return {
        "title": f"{law_name} {article} ({heading.group(2)})",
        "law": law_name,
        "article": article,
        "heading": heading.group(2),
        "effective_date": f"{year}-{int(month):02d}-{int(day):02d}",
        "promulgation": promulgation,
        "url": shortcut,
        "text": "\n".join(lines),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    failed = 0
    for law, article, slug, categories in ARTICLES:
        try:
            item = fetch(law, article)
        except Exception as error:  # keep going so one bad article does not hide the rest
            print(f"FAIL {law} {article}: {error}", file=sys.stderr)
            failed += 1
            continue
        front = "\n".join(f"{key}: {item[key]}" for key in ("title", "law", "article", "effective_date", "promulgation", "url"))
        (OUT / f"{slug}.md").write_text(
            f"---\n{front}\ndocument_type: statute\ncategories: {categories}\n---\n{item['text']}\n", encoding="utf-8")
        print(f"ok   {item['title']}  [시행 {item['effective_date']}]  {len(item['text'])}자")
        time.sleep(1)  # be gentle with the public site
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
