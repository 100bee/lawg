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
    # --- added 2026-11-12 from docs/stage0/statute-candidates.md, priority A ---
    ("형사소송법", "제223조", "criminal-procedure-223", "fraud,insult,defamation,obscenity,account,threat"),
    ("형사소송법", "제230조", "criminal-procedure-230", "insult,defamation"),
    ("형사소송법", "제232조", "criminal-procedure-232", "insult,defamation,threat"),
    ("형사소송법", "제237조", "criminal-procedure-237", "fraud,insult,defamation,obscenity,account,threat"),
    ("형법", "제9조", "criminal-9", "fraud,insult,defamation,obscenity,account,threat"),
    ("소년법", "제4조", "juvenile-4", "fraud,insult,defamation,obscenity,account,threat"),
    ("민법", "제750조", "civil-750", "fraud,insult,defamation,obscenity,account,threat"),
    ("소송촉진법", "제25조", "litigation-promotion-25", "fraud,obscenity,threat"),
    ("형법", "제352조", "criminal-352", "fraud,threat"),
    ("정보통신망법", "제44조의2", "network-44-2", "insult,defamation"),
    ("성폭력처벌법", "제42조", "sexual-violence-42", "obscenity"),
    ("정보통신망법", "제49조의2", "network-49-2", "account"),
    ("정보통신망법", "제72조", "network-72", "account"),
    ("형법", "제350조", "criminal-350", "threat,fraud"),
    ("형법", "제324조", "criminal-324", "threat"),
    ("스토킹처벌법", "제4조", "stalking-4", "threat"),
    # --- priority B ---
    ("형사소송법", "제225조", "criminal-procedure-225", "fraud,insult,defamation,obscenity,account,threat"),
    ("형사소송법", "제234조", "criminal-procedure-234", "fraud,insult,defamation,obscenity,account,threat"),
    ("형사소송법", "제245조의7", "criminal-procedure-245-7", "fraud,insult,defamation,obscenity,account,threat"),
    ("형사소송법", "제249조", "criminal-procedure-249", "fraud,insult,defamation,obscenity,account,threat"),
    ("형사소송법", "제327조", "criminal-procedure-327", "insult,defamation,threat"),
    ("형사소송법", "제243조의2", "criminal-procedure-243-2", "fraud,insult,defamation,obscenity,account,threat"),
    ("학교폭력예방법", "제2조", "school-violence-2", "insult,defamation,obscenity,threat"),
    ("형법", "제25조", "criminal-25", "fraud,threat"),
    ("형법", "제30조", "criminal-30", "fraud,insult,defamation,obscenity,account,threat"),
    ("형법", "제32조", "criminal-32", "fraud,insult,defamation,account"),
    ("형법", "제51조", "criminal-51", "fraud,insult,defamation,obscenity,account,threat"),
    ("형법", "제156조", "criminal-156", "fraud,insult,defamation,obscenity,account,threat"),
    ("민법", "제751조", "civil-751", "insult,defamation,obscenity,threat"),
    ("민법", "제766조", "civil-766", "fraud,insult,defamation,obscenity,account,threat"),
    ("소송촉진법", "제26조", "litigation-promotion-26", "fraud,obscenity,threat"),
    ("형법", "제355조", "criminal-355", "fraud"),
    ("게임산업법", "제32조", "game-industry-32", "fraud,account"),
    ("게임산업법 시행령", "제18조의4", "game-industry-decree-18-4", "fraud"),
    ("게임산업법", "제44조", "game-industry-44", "fraud"),
    ("정보통신망법", "제44조의3", "network-44-3", "insult,defamation"),
    ("정보통신망법", "제44조의6", "network-44-6", "insult,defamation"),
    ("민법", "제764조", "civil-764", "defamation"),
    ("청소년성보호법", "제15조의2", "youth-sex-protection-15-2", "obscenity"),
    ("아동복지법", "제17조", "child-welfare-17", "obscenity,insult"),
    ("아동복지법", "제71조", "child-welfare-71", "obscenity,insult"),
    ("성폭력처벌법", "제14조", "sexual-violence-14", "obscenity"),
    ("성폭력처벌법", "제14조의2", "sexual-violence-14-2", "obscenity"),
    ("성폭력처벌법", "제14조의3", "sexual-violence-14-3", "obscenity,threat"),
    ("청소년성보호법", "제11조", "youth-sex-protection-11", "obscenity"),
    ("정보통신망법", "제73조", "network-73", "account,insult,defamation"),
    ("정보통신망법", "제70조의2", "network-70-2", "account"),
    ("형법", "제314조", "criminal-314", "account"),
    ("게임산업법", "제45조", "game-industry-45", "account"),
    ("게임산업법", "제46조", "game-industry-46", "account"),
    ("개인정보 보호법", "제2조", "personal-info-2", "threat,defamation"),
    ("개인정보 보호법", "제59조", "personal-info-59", "threat,defamation,account"),
    ("개인정보 보호법", "제71조", "personal-info-71", "threat,defamation,account"),
    ("개인정보 보호법", "제72조", "personal-info-72", "account"),
    ("통신비밀보호법", "제14조", "comm-secrets-14", "fraud,insult,defamation,obscenity,account,threat"),
    ("통신비밀보호법", "제16조", "comm-secrets-16", "fraud,insult,defamation,obscenity,account,threat"),
    ("형법", "제324조의5", "criminal-324-5", "threat"),
    ("형법", "제286조", "criminal-286", "threat"),
    ("스토킹처벌법", "제3조", "stalking-3", "threat"),
    ("스토킹처벌법", "제8조", "stalking-8", "threat"),
    ("스토킹처벌법", "제9조", "stalking-9", "threat"),
    ("스토킹처벌법", "제20조", "stalking-20", "threat"),
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
