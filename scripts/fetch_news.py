#!/usr/bin/env python3
"""ED Khabar: Google News RSS se Enforcement Directorate ki khabrein laakar news.json update karta hai.

Sirf Python standard library use hoti hai, koi install nahi chahiye.
Chalane ke liye:  python scripts/fetch_news.py
"""
import datetime as dt
import email.utils
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "news.json")
KEEP_DAYS = 45          # itne din purani khabrein rakhi jayengi
MAX_ITEMS = 300

# (language, hl, ceid, query)
FEEDS = [
    ("en", "en-IN", "IN:en", '"Enforcement Directorate" when:7d'),
    ("en", "en-IN", "IN:en", '"ED" (PMLA OR FEMA OR "money laundering") when:7d'),
    ("en", "en-IN", "IN:en", '"Enforcement Directorate" ("said in a statement" OR "ED said" OR "press release" OR "statement") when:7d'),
    ("hi", "hi", "IN:hi", '"प्रवर्तन निदेशालय" OR "ईडी" छापेमारी OR "ED" PMLA when:7d'),
]

CATEGORIES = [
    ("Arrests", r"arrest|custody|nabbed|held|गिरफ्तार|गिरफ़्तार|हिरासत"),
    ("Summons", r"summon|questioning|questioned|appear|grill|समन|पूछताछ"),
    ("Attachments", r"attach|seiz|freez|confiscat|कुर्क|ज़ब्त|जब्त"),
    ("Court", r"court|bail|prosecution complaint|charge ?sheet|chargesheet|tribunal|\bHC\b|\bSC\b|अदालत|कोर्ट|जमानत|ज़मानत|आरोप पत्र"),
    ("Raids", r"raid|search|छापा|छापे|छापेमारी|तलाशी"),
    ("FEMA", r"\bFEMA\b|foreign exchange|hawala|विदेशी मुद्रा|हवाला"),
]

# ED se related hone ka check (taaki "ED" shabd wali galat khabrein na aayein)
ED_RE = re.compile(r"enforcement directorate|प्रवर्तन निदेशालय|\bED\b|ईडी|PMLA|money laundering|मनी लॉन्ड्रिंग", re.I)


def feed_url(hl, ceid, q):
    params = {"q": q, "hl": hl, "gl": "IN", "ceid": ceid}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ED-Khabar-bot", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


# Headline mein ED ke apne bayan ka zikr ho to "ED statement" label lagta hai
STATEMENT_RE = re.compile(
    r"\bED (said|says|stated|claims|alleges|told)\b|according to (the )?ED\b|\bED statement|"
    r"statement|press release|\bED:|ईडी ने कहा|ईडी का दावा|ईडी के मुताबिक|ईडी के अनुसार|बयान",
    re.I)


def categorize(text):
    for name, pattern in CATEGORIES:
        if re.search(pattern, text, re.I):
            return name
    return "Other"


def norm(title):
    return re.sub(r"[^\w]+", "", title.lower())[:90]


def parse_rss(xml_bytes, lang):
    items = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        # Google News title format: "Headline - Source"
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)].strip()
        pub = it.findtext("pubDate")
        try:
            when = email.utils.parsedate_to_datetime(pub).astimezone(dt.timezone.utc)
        except Exception:
            when = dt.datetime.now(dt.timezone.utc)
        if not title or not link or not ED_RE.search(title):
            continue
        items.append({
            "title": title,
            "url": link,
            "source": source or "News",
            "lang": lang,
            "published": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "category": categorize(title),
        })
    return items


# ---------- ED ki official website (press releases) ----------
ED_PAGES = [
    "https://enforcementdirectorate.gov.in/press-release",
    "https://enforcementdirectorate.gov.in/press-release?page=1",
]
ED_DATE = re.compile(r"(\d{1,2})/([A-Za-z]{3})[a-z]*/(\d{4})")
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class _Rows(HTMLParser):
    """Har <tr> ke cells ka text aur usme ke links jama karta hai."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.links, self.in_cell = [], None, [], [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row, self.links = [], []
        elif tag in ("td", "th") and self.row is not None:
            self.in_cell, self.cell = True, []
        elif tag == "a" and self.row is not None:
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.row is not None and self.in_cell:
            self.row.append(" ".join("".join(self.cell).split()))
            self.in_cell = False
        elif tag == "tr" and self.row is not None:
            self.rows.append((self.row, self.links))
            self.row = None

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)


def parse_ed_releases(html_text, page_url):
    p = _Rows()
    p.feed(html_text)
    items = []
    for cells, links in p.rows:
        date_cell = next((c for c in cells if ED_DATE.fullmatch(c.strip())), None)
        if not date_cell:
            continue
        d, mon, y = ED_DATE.fullmatch(date_cell.strip()).groups()
        month = MONTHS.get(mon.lower())
        if not month:
            continue
        # sabse lamba cell = description
        desc = max((c for c in cells if c != date_cell), key=len, default="")
        if len(desc) < 25:
            continue
        title = desc if len(desc) <= 230 else desc[:227].rsplit(" ", 1)[0] + "…"
        pdf = next((l for l in links if l.lower().split("?")[0].endswith(".pdf")), links[0] if links else None)
        url = urllib.parse.urljoin(page_url, pdf) if pdf else page_url
        # 12:00 IST = 06:30 UTC
        when = dt.datetime(int(y), month, int(d), 6, 30, tzinfo=dt.timezone.utc)
        items.append({
            "title": title,
            "url": url,
            "source": "enforcementdirectorate.gov.in",
            "lang": "en",
            "official": True,
            "published": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "category": categorize(title),
        })
    return items


def fetch_ed_releases():
    items = []
    for url in ED_PAGES:
        try:
            raw = fetch(url).decode("utf-8", "replace")
            got = parse_ed_releases(raw, url)
            print(f"ED website: {len(got)} press releases ({url})")
            items += got
        except Exception as e:
            print(f"[warn] ED website fail ({url}): {e}", file=sys.stderr)
    return items


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def main():
    fresh, ok = [], 0
    for lang, hl, ceid, q in FEEDS:
        try:
            fresh += parse_rss(fetch(feed_url(hl, ceid, q)), lang)
            ok += 1
        except Exception as e:
            print(f"[warn] feed fail ({lang}): {e}", file=sys.stderr)

    ed = fetch_ed_releases()
    if ed:
        fresh += ed
        ok += 1

    if ok == 0:
        print("Koi feed nahi mila, purani news.json waisi hi rahegi.")
        return 0

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)
    merged, seen = [], set()
    for item in sorted(fresh + load_existing(), key=lambda x: x["published"], reverse=True):
        item["category"] = categorize(item["title"])
        if not item.get("official"):
            item["statement"] = bool(STATEMENT_RE.search(item["title"]))
        key = norm(item["title"])
        if key in seen:
            continue
        try:
            when = dt.datetime.strptime(item["published"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        except Exception:
            continue
        if when < cutoff and not item.get("pinned"):
            continue
        seen.add(key)
        merged.append(item)

    data = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": merged[:MAX_ITEMS],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(fresh)} nayi entries mili, kul {len(data['items'])} khabrein save hui.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
