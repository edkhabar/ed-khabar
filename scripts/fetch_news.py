#!/usr/bin/env python3
"""ED Khabar: Google News RSS se Enforcement Directorate ki khabrein laakar
news.json, har khabar ka apna page (story/<id>.html) aur sitemap.xml banata hai.

Sirf Python standard library use hoti hai, koi install nahi chahiye.
Chalane ke liye:  python scripts/fetch_news.py
"""
import datetime as dt
import email.utils
import glob
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "news.json")
STORY_DIR = os.path.join(ROOT, "story")
SITEMAP = os.path.join(ROOT, "sitemap.xml")
SITE = "https://edkhabar.in"
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

# Headline mein ED ke apne bayan ka zikr ho to "ED statement" label lagta hai
STATEMENT_RE = re.compile(
    r"\bED (said|says|stated|claims|alleges|told)\b|according to (the )?ED\b|\bED statement|"
    r"statement|press release|\bED:|ईडी ने कहा|ईडी का दावा|ईडी के मुताबिक|ईडी के अनुसार|बयान",
    re.I)

# Ek hi case ki khabrein milane ke liye: yeh aam shabd nahi gine jaate
STOP = set("""
ed enforcement directorate agency probe probes case cases money laundering pmla fema raid raids raided search searches
searched conducts conducted arrests arrested arrest summons summoned attaches attached attachment seized seizes worth crore
lakh rs over against linked with from into under after for the and of in on at to by a an as its his her their former
ex alleged allegedly scam fraud news says said statement court bail premises locations location properties property assets
asset multiple several new latest also more than issue issues files filed complaint prosecution official officials team
chief minister deputy leader party businessman businessmen promoter promoters group company firm director directors days
week weeks months day two three four five six seven eight nine ten grants granted sent remand custody before appear appears
""".split())
STOP_HI = set("ईडी प्रवर्तन निदेशालय ने की के का को में पर से और एक मामले मामला छापेमारी करोड़ लाख".split())


def feed_url(hl, ceid, q):
    params = {"q": q, "hl": hl, "gl": "IN", "ceid": ceid}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ED-Khabar-bot; +https://edkhabar.in)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def categorize(text):
    for name, pattern in CATEGORIES:
        if re.search(pattern, text, re.I):
            return name
    return "Other"


def norm(title):
    return re.sub(r"[^\w]+", "", title.lower())[:90]


def story_id(url):
    """URL se chhota, hamesha same rehne wala id (FNV-1a, 32 bit)."""
    h = 0x811C9DC5
    for ch in url:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, "08x")


def keywords(item):
    words = re.findall(r"[\wऀ-ॿ]+", item["title"].lower())
    stop = STOP_HI if item.get("lang") == "hi" else STOP
    return {w for w in words if len(w) >= 3 and w not in stop and not w.isdigit()}


def related_groups(items):
    """Milti-julti headlines (3 din ke andar, same bhasha) ko ek case maanta hai."""
    group = {}
    heads = []  # (head_id, keywords, time, lang)
    for it in items:  # items: newest first
        kw = keywords(it)
        t = dt.datetime.strptime(it["published"], "%Y-%m-%dT%H:%M:%SZ")
        best, score = None, 0.0
        for hid, hkw, ht, hl in heads:
            if hl != it.get("lang") or abs((ht - t).total_seconds()) > 3 * 86400 or not kw or not hkw:
                continue
            inter = len(kw & hkw)
            # 3+ khaas shabd common (jaise naam), ya 2 common aur chhoti headline ka bada hissa
            s = 1.0 + inter if inter >= 3 else (inter / min(len(kw), len(hkw)) if inter >= 2 else 0)
            if s > score:
                best, score = hid, s
        if best and score >= 0.6:
            group[it["id"]] = best
        else:
            group[it["id"]] = it["id"]
            heads.append((it["id"], kw, t, it.get("lang")))
    return group


def parse_rss(xml_bytes, lang):
    items = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        site = (src_el.get("url") or "").strip() if src_el is not None else ""
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
            "site": urllib.parse.urlparse(site).netloc if site else "",
            "lang": lang,
            "published": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "category": categorize(title),
        })
    return items


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


# ---------------- har khabar ka page ----------------
STORY_CSS = """
:root{--navy:#14213d;--ink:#16203a;--paper:#f7f5f0;--card:#fff;--muted:#5f6878;--line:#e5e0d6;--accent:#d9480f;--peach:#ffb38a}
@media(prefers-color-scheme:dark){:root{--ink:#e7eaf1;--paper:#0e1422;--card:#172036;--muted:#97a0b3;--line:#27324b;--accent:#f26a2e}}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,system-ui,-apple-system,'Segoe UI','Noto Sans Devanagari',sans-serif;background:var(--paper);color:var(--ink);line-height:1.6}
header{background:var(--navy);color:#fff}
.in{max-width:760px;margin:0 auto;padding:0 18px}
header .in{display:flex;align-items:center;gap:12px;padding:14px 18px}
header a{color:#fff;text-decoration:none;font-family:Georgia,serif;font-weight:700;font-size:1.35rem}
header a span{color:var(--peach)}
.mk{width:38px;height:38px;border-radius:9px;background:#1d2f57;display:grid;place-items:center;font-family:Georgia,serif;font-weight:700;color:#fff;font-size:.95rem;border-bottom:3px solid var(--accent)}
main.in{padding:24px 18px 44px}
.crumb{font-size:.85rem;margin-bottom:16px}.crumb a{color:var(--accent);text-decoration:none}
.meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:.82rem;color:var(--muted);margin-bottom:10px}
.tag{font-weight:700;font-size:.72rem;text-transform:uppercase;letter-spacing:.03em;padding:3px 8px;border-radius:5px;background:#fff0e6;color:var(--accent)}
h1{font-family:Georgia,'Noto Serif Devanagari',serif;font-size:1.75rem;line-height:1.3;margin-bottom:18px}
.go{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;font-weight:700;padding:12px 18px;border-radius:10px}
.note{font-size:.85rem;color:var(--muted);margin-top:14px}
.share{display:flex;gap:8px;margin-top:18px;flex-wrap:wrap}
.share a{border:1px solid var(--line);background:var(--card);color:var(--ink);text-decoration:none;font-size:.88rem;font-weight:600;padding:8px 12px;border-radius:8px}
h2{font-family:Georgia,serif;font-size:1.15rem;margin:34px 0 12px}
.rel a{display:block;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 14px;margin-bottom:8px;text-decoration:none;color:var(--ink)}
.rel small{display:block;color:var(--muted);font-size:.8rem}
footer{background:var(--navy);color:#c9d1e3;font-size:.82rem;padding:20px 0}
footer a{color:var(--peach)}
"""


def ist(iso):
    t = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %I:%M %p IST")


def story_page(it, related):
    e = html.escape
    title, desc = e(it["title"]), e(f'{it["title"]} — reported by {it["source"]}. Latest Enforcement Directorate news on ED Khabar.')
    canon = f'{SITE}/story/{it["id"]}.html'
    lang = "hi" if it.get("lang") == "hi" else "en"
    share_text = urllib.parse.quote(f'{it["title"]} — via ED Khabar\n{canon}')
    rel_html = ""
    if related:
        rel_html = "<h2>More reports on this story</h2><div class=\"rel\">" + "".join(
            f'<a href="{e(r["id"])}.html">{e(r["title"])}<small>{e(r["source"])} · {ist(r["published"])}</small></a>'
            for r in related) + "</div>"
    badge = "Official" if it.get("official") else ("ED statement" if it.get("statement") else "")
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | ED Khabar</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canon}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="ED Khabar">
<meta property="og:title" content="{title}">
<meta property="og:description" content="Reported by {e(it["source"])} · {e(it["category"])} · ED Khabar">
<meta property="og:url" content="{canon}">
<meta property="og:image" content="{SITE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta property="article:published_time" content="{it["published"]}">
<link rel="icon" href="../icons/icon-192.png" type="image/png">
<style>{STORY_CSS}</style>
</head>
<body>
<header><div class="in"><div class="mk">ED</div><a href="../">ED <span>Khabar</span></a></div></header>
<main class="in">
  <div class="crumb"><a href="../">← All ED news</a></div>
  <div class="meta"><span class="tag">{e(it["category"])}</span>{f'<span class="tag">{badge}</span>' if badge else ''}<span>{e(it["source"])}</span><span>· {ist(it["published"])}</span></div>
  <h1>{title}</h1>
  <a class="go" href="{e(it["url"])}" rel="noopener">Read the full story at {e(it["source"])} →</a>
  <p class="note">This headline was reported by {e(it["source"])}. ED Khabar links to the original report and does not publish its content.</p>
  <div class="share">
    <a href="https://wa.me/?text={share_text}" target="_blank" rel="noopener">Share on WhatsApp</a>
    <a href="https://twitter.com/intent/tweet?text={urllib.parse.quote(it["title"] + " — via ED Khabar")}&url={urllib.parse.quote(canon)}" target="_blank" rel="noopener">Share on X</a>
  </div>
  {rel_html}
</main>
<footer><div class="in">ED Khabar is an independent news aggregator, not affiliated with the Directorate of Enforcement or the Government of India. <a href="../">Home</a></div></footer>
</body>
</html>
"""


def write_pages(items, group):
    os.makedirs(STORY_DIR, exist_ok=True)
    members = {}
    for it in items:
        members.setdefault(group[it["id"]], []).append(it)
    keep = set()
    for it in items:
        related = [r for r in members[group[it["id"]]] if r["id"] != it["id"]][:8]
        path = os.path.join(STORY_DIR, it["id"] + ".html")
        content = story_page(it, related)
        keep.add(path)
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = f.read()
        if old != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
    for path in glob.glob(os.path.join(STORY_DIR, "*.html")):
        if path not in keep:
            os.remove(path)   # 45 din se purani khabron ke page hata do

    urls = [f"  <url><loc>{SITE}/</loc><changefreq>hourly</changefreq><priority>1.0</priority></url>"]
    for it in items:
        urls.append(f'  <url><loc>{SITE}/story/{it["id"]}.html</loc><lastmod>{it["published"][:10]}</lastmod></url>')
    with open(SITEMAP, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + "\n".join(urls) + "\n</urlset>\n")


def main():
    fresh, ok = [], 0
    for lang, hl, ceid, q in FEEDS:
        try:
            fresh += parse_rss(fetch(feed_url(hl, ceid, q)), lang)
            ok += 1
        except Exception as e:
            print(f"[warn] feed fail ({lang}): {e}", file=sys.stderr)

    if ok == 0:
        print("Koi feed nahi mila, purani news.json waisi hi rahegi.")
        return 0

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)
    merged, seen = [], set()
    for item in sorted(fresh + load_existing(), key=lambda x: x["published"], reverse=True):
        item["category"] = categorize(item["title"])
        if not item.get("official"):
            item["statement"] = bool(STATEMENT_RE.search(item["title"]))
        item["id"] = story_id(item["url"])
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

    items = merged[:MAX_ITEMS]
    group = related_groups(items)
    for it in items:
        it["group"] = group[it["id"]]
    write_pages(items, group)

    data = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": items,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(fresh)} nayi entries mili, kul {len(items)} khabrein save hui, "
          f"{len(set(group.values()))} alag cases.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
