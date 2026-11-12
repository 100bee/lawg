"""Fetch precedents from law.go.kr into backend/data/sources/ (one case per file).

usage: python3 scripts/fetch_precedents.py 2022도10688:obscenity 2011도15631:insult,defamation ...
       python3 scripts/fetch_precedents.py   (no arguments: refresh every precedent-*.md already in sources)
The body is the 판결요지 copied verbatim; cases without one fall back to the 판시사항 (marked in front matter).
shortcut: scrapes the public case page; switch to the Open API (LAW_API_OC) once it is approved.
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


def get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (lawg precedent fetch)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def text_of(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>|</p>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    return "\n".join(re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines() if line.strip())


def majority_only(text: str) -> str:
    """Drop en banc dissents/concurrences ("[대법관 … 반대의견] …") up to the next numbered point; the rest stays verbatim."""
    kept, skipping = [], False
    for line in text.splitlines():
        if re.match(r"\[\d+\]", line):
            skipping = False
        if re.match(r"(?:\[\d+\]\s*)?\[대법관[^\]]*의견\]", line):
            skipping = True
        if not skipping:
            kept.append(line)
    return "\n".join(kept)


assert majority_only("[1] [다수의견] a\nb\n[대법관 갑의 반대의견] c\nd\n[2] [다수의견] e\n[대법관 갑의 반대의견] f") == \
    "[1] [다수의견] a\nb\n[2] [다수의견] e"


CASE_LETTERS = {"고정": "gojeong", "고단": "godan", "고합": "gohap", "도": "do", "노": "no", "다": "da", "두": "du"}


def slug(case_number: str) -> str:
    """ASCII file name (2022도10688 -> 2022do10688) so clones on any OS see the same path."""
    for letters, latin in CASE_LETTERS.items():
        case_number = case_number.replace(letters, latin)
    if not case_number.isascii():
        raise ValueError(f"{case_number}: add its case letters to CASE_LETTERS")
    return case_number


assert slug("2014고정1619") == "2014gojeong1619" and slug("90도2102") == "90do2102"


def fetch(case_number: str) -> dict:
    shortcut = f"{BASE}/{urllib.parse.quote(f'판례/({case_number})')}"
    frame = re.search(r'src="([^"]*precInfoP\.do[^"]+)"', get(shortcut))
    if not frame:
        raise ValueError(f"{case_number}: case page not found")
    page = get(BASE + html.unescape(frame.group(1)))
    # e.g. [대법원 2020. 11. 19. 선고 2020도5813 전원합의체 판결], [의정부지법 2014. 10. 23. 선고 2014고정1619 판결 : 항소]
    header = re.search(r'<div class="subtit1">\s*\[(\S+)\s+(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*선고\s+(\S+)\s+'
                       r'([^\]:]+?)\s*(?::[^\]]*)?\]', page)
    if not header or header.group(5) != case_number:
        raise ValueError(f"{case_number}: unexpected page header")
    court, year, month, day, _, kind = header.groups()
    sections = dict(re.findall(r"<h4[^>]*>【([^】]+)】</h4>(.*?)(?=<h4|<!--\s*본문|$)", page, re.S))
    section = "판결요지" if text_of(sections.get("판결요지", "")) else "판시사항"
    body = majority_only(text_of(sections.get(section, "")))
    if not body:
        raise ValueError(f"{case_number}: neither 판결요지 nor 판시사항 found")
    decided_on = f"{year}-{int(month):02d}-{int(day):02d}"
    return {"title": f"{court} {case_number} {kind} ({year}. {int(month)}. {int(day)}.)", "court": court,
            "case_number": case_number, "decided_on": decided_on, "section": section, "url": shortcut, "text": body}


def existing() -> list[str]:
    """case:categories for every precedent already in sources, so a bare run refreshes them all."""
    found = []
    for path in sorted(OUT.glob("precedent-*.md")):
        front = dict(line.split(": ", 1) for line in path.read_text(encoding="utf-8").split("---")[1].strip().splitlines())
        found.append(f"{front['case_number']}:{front['categories']}")
    return found


def main(arguments: list[str]) -> int:
    arguments = arguments or existing()
    if not arguments:
        print(__doc__)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    failed = 0
    for argument in arguments:
        case_number, _, categories = argument.partition(":")
        try:
            item = fetch(case_number)
        except Exception as error:  # keep going so one bad case does not hide the rest
            print(f"FAIL {case_number}: {error}", file=sys.stderr)
            failed += 1
            continue
        front = "\n".join(f"{key}: {item[key]}" for key in ("title", "court", "case_number", "decided_on", "section", "url"))
        (OUT / f"precedent-{slug(case_number)}.md").write_text(
            f"---\n{front}\ndocument_type: precedent\ncategories: {categories}\n---\n{item['text']}\n", encoding="utf-8")
        print(f"ok   {item['title']}  [{item['section']}]  {len(item['text'])}자")
        time.sleep(1.5)  # be gentle with the public site
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
