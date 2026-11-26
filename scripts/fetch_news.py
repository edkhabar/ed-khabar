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


# ---------- ED ki official press releases (ED ki email se mili ijazat ke saath) ----------
ED_API = "https://www.enforcementdirectorate.gov.in/umbraco/backoffice/api/PressReleaseApi/GetPublic?language=en"
ED_SITE = "https://www.enforcementdirectorate.gov.in"
ED_EVERY_HOURS = 6       # ED ke server par bojh na pade: 6 ghante mein sirf ek baar
ED_MAX = 40              # sirf sabse nayi itni releases
ED_HEADERS = {
    "User-Agent": "ED-Khabar/1.0 (+https://edkhabar.in; independent news aggregator, fetching with ED's permission)",
    "Accept": "application/json",
}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _ed_when(rec):
    """CreatedDate ('2026-11-25 17:15:27', IST) ho to woh, warna ReleaseDate ka 12 baje IST."""
    for key, fmt in (("CreatedDate", "%Y-%m-%d %H:%M:%S"), ("ReleaseDate", "%Y-%m-%dT%H:%M:%S")):
        val = (rec.get(key) or "").split(".")[0]
        try:
            t = dt.datetime.strptime(val, fmt)
        except ValueError:
            continue
        if key == "ReleaseDate":
            t = t.replace(hour=12)
        return t.replace(tzinfo=IST).astimezone(dt.timezone.utc)
    return None


def parse_ed_api(records):
    items = []
    recs = [r for r in records if isinstance(r, dict) and (r.get("Language") or "en") == "en"]
    recs.sort(key=lambda r: (r.get("ReleaseDate") or "", r.get("Id") or 0), reverse=True)
    for r in recs[:ED_MAX]:
        desc = " ".join((r.get("Description") or "").split())
        when = _ed_when(r)
        if len(desc) < 20 or not when:
            continue
        title = desc if len(desc) <= 230 else desc[:227].rsplit(" ", 1)[0] + "…"
        pdf = r.get("PdfUrl") or ""
        url = urllib.parse.urljoin(ED_SITE + "/", urllib.parse.quote(pdf, safe="/:%?=&")) if pdf \
            else ED_SITE + "/media/press-release/"
        items.append({
            "title": title, "url": url, "source": "ED press release",
            "lang": "en", "official": True,
            "published": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "category": categorize(title),
        })
    return items


def fetch_ed_releases(last_iso):
    """6 ghante mein ek baar hi ED se maangta hai. (items, naya last_iso) lautata hai."""
    now = dt.datetime.now(dt.timezone.utc)
    try:
        last = dt.datetime.strptime(last_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        if now - last < dt.timedelta(hours=ED_EVERY_HOURS):
            print("ED press releases: abhi skip (6 ghante wala niyam)")
            return [], last_iso
    except (TypeError, ValueError):
        pass
    try:
        req = urllib.request.Request(ED_API, headers=ED_HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        items = parse_ed_api(data if isinstance(data, list) else data.get("items", []))
        print(f"ED press releases: {len(items)} li gayi")
        return items, now.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:
        print(f"[warn] ED press releases fail: {e}", file=sys.stderr)
        return [], last_iso


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def load_ed_last():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f).get("ed_last")
    except Exception:
        return None


def main():
    fresh, ok = [], 0
    for lang, hl, ceid, q in FEEDS:
        try:
            fresh += parse_rss(fetch(feed_url(hl, ceid, q)), lang)
            ok += 1
        except Exception as e:
            print(f"[warn] feed fail ({lang}): {e}", file=sys.stderr)

    ed_items, ed_last = fetch_ed_releases(load_ed_last())
    if ed_items:
        fresh += ed_items
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
        "ed_last": ed_last,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(fresh)} nayi entries mili, kul {len(data['items'])} khabrein save hui.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
