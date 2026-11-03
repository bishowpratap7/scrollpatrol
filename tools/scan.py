#!/usr/bin/env python3
"""Scroll Patrol scanner: fetches trending social posts from public feeds
(no API keys, no logins) and writes data/posts.json, then bakes the latest
haul into index.html and regenerates feed.xml + sitemap.xml.
Each section fails independently: on failure it keeps the previous data
and is flagged stale. Stdlib only."""
import json, os, re, subprocess, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "posts.json")
SITE = "https://bishowpratap7.github.io/scrollpatrol/"
UA = {"User-Agent": "ScrollPatrol/1.0 (by Bishow Pandey; +https://x.com/bishowppandey)"}

QUIPS = {
    "most_wanted": ["All suspects are trending until proven funny.",
                    "Booked for excessive virality. No bail.",
                    "Caught red-handed farming engagement."],
    "meme_stash": ["Evidence bags full of memes. Again.",
                   "Contraband humor, seized hourly.",
                   "The stash grows. Nobody snitches."],
    "elsewhere": ["Other platforms are talking. We listen so you don't have to.",
                  "Witness reports from across the social streets.",
                  "They post there. The party, however, is on X."],
    "interrogation": ["Under the lamp, every joke talks.",
                      "We asked the jokes nicely. They confessed.",
                      "No dad joke survives interrogation."],
}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def fetch(url, accept="application/json", timeout=20):
    req = urllib.request.Request(url, headers={**UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        # Some networks/proxies drop urllib TLS; curl is the fallback.
        out = subprocess.run(["curl", "-s", "--max-time", str(timeout), "-A", UA["User-Agent"],
                              "-H", f"Accept: {accept}", url],
                             capture_output=True, text=True)
        if out.returncode != 0 or not out.stdout:
            raise RuntimeError(f"fetch failed: {url}")
        return out.stdout

def fetch_json(url):
    return json.loads(fetch(url))

def strip_html(s):
    s = re.sub(r"<br\s*/?>", " ", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()

# ---------- sections ----------
def scan_reddit():
    items, seen = [], set()
    ATOM = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/"}
    for sub in ("popular", "funny", "ProgrammerHumor"):
        got = []
        try:
            d = fetch_json(f"https://www.reddit.com/r/{sub}/hot.json?limit=9&raw_json=1")
            for ch in d.get("data", {}).get("children", []):
                p = ch.get("data", {})
                if p.get("stickied"):
                    continue
                dest = str(p.get("url_overridden_by_dest", ""))
                img = dest if dest.lower().endswith((".jpg", ".jpeg", ".png", ".gif")) else ""
                got.append({"source": "Reddit", "sub": "r/" + sub, "title": p.get("title", ""),
                            "url": "https://www.reddit.com" + p.get("permalink", ""),
                            "score": p.get("score", 0), "comments": p.get("num_comments", 0), "image": img})
        except Exception as e:
            print(f"  reddit json r/{sub}: {e}", file=sys.stderr)
        if not got:
            try:
                raw = fetch(f"https://www.reddit.com/r/{sub}/.rss", accept="application/rss+xml")
                root = ET.fromstring(raw)
                for e in root.findall("a:entry", ATOM)[:9]:
                    t = e.find("a:title", ATOM); l = e.find("a:link", ATOM)
                    if t is None or l is None:
                        continue
                    thumb = e.find("m:thumbnail", ATOM)
                    got.append({"source": "Reddit", "sub": "r/" + sub, "title": t.text or "",
                                "url": l.get("href", ""), "score": 0, "comments": 0,
                                "image": thumb.get("url", "") if thumb is not None else ""})
            except Exception as e:
                print(f"  reddit rss r/{sub}: {e}", file=sys.stderr)
        for it in got:
            if it["url"] and it["url"] not in seen:
                seen.add(it["url"]); items.append(it)
    if not items:
        raise RuntimeError("reddit returned nothing")
    items.sort(key=lambda x: -x["score"])
    return items[:12]

def scan_memes():
    items, seen = [], set()
    for sub, n in (("ProgrammerHumor", 6), ("memes", 6), ("dankmemes", 4)):
        try:
            d = fetch_json(f"https://meme-api.com/gimme/{sub}/{n}")
            for m in d.get("memes", []):
                if m.get("nsfw") or m.get("url") in seen:
                    continue
                seen.add(m.get("url"))
                items.append({"title": m.get("title", ""), "image": m.get("url", ""),
                              "url": m.get("postLink", ""), "ups": m.get("ups", 0), "sub": "r/" + sub})
        except Exception as e:
            print(f"  meme-api {sub}: {e}", file=sys.stderr)
    if not items:
        raise RuntimeError("meme-api returned nothing")
    return items[:12]

def scan_elsewhere():
    items = []
    try:
        d = fetch_json("https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrendingTopics?limit=12")
        for t in d.get("topics", []):
            items.append({"kind": "Bluesky trend", "text": t.get("topic", ""),
                          "author": "", "url": "https://bsky.app" + t.get("link", ""), "likes": 0, "image": ""})
    except Exception as e:
        print(f"  bluesky: {e}", file=sys.stderr)
    try:
        d = fetch_json("https://lemmy.world/api/v3/post/list?type_=All&sort=Hot&limit=10")
        for w in d.get("posts", []):
            p = w.get("post", {}); c = w.get("counts", {}); comm = w.get("community", {})
            items.append({"kind": "Lemmy post", "text": p.get("name", ""),
                          "author": comm.get("title") or comm.get("name", ""),
                          "url": p.get("ap_id") or p.get("url", ""), "likes": c.get("score", 0),
                          "image": p.get("thumbnail_url", "") or ""})
    except Exception as e:
        print(f"  lemmy: {e}", file=sys.stderr)
    if not items:
        raise RuntimeError("elsewhere returned nothing")
    return items[:16]

def scan_jokes():
    items = []
    try:
        d = fetch_json("https://v2.jokeapi.dev/joke/Programming?type=single&amount=6&safe-mode")
        jokes = d.get("jokes", [d]) if isinstance(d, dict) else []
        for j in jokes:
            if j.get("joke"):
                items.append({"text": j["joke"], "source": "Programming joke"})
    except Exception as e:
        print(f"  jokeapi: {e}", file=sys.stderr)
    for _ in range(3):
        try:
            d = fetch_json("https://icanhazdadjoke.com/")
            if d.get("joke"):
                items.append({"text": d["joke"], "source": "Dad joke"})
        except Exception as e:
            print(f"  dadjoke: {e}", file=sys.stderr)
    if not items:
        raise RuntimeError("no jokes confessed")
    return items

SCANNERS = {"most_wanted": scan_reddit, "meme_stash": scan_memes,
            "elsewhere": scan_elsewhere, "interrogation": scan_jokes}

def main():
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT)).get("sections", {})
        except Exception:
            prev = {}
    sections, report = {}, []
    for name, fn in SCANNERS.items():
        try:
            sections[name] = {"fetched_at": now_iso(), "stale": False, "items": fn()}
            report.append(f"{name}: OK ({len(sections[name]['items'])})")
        except Exception as e:
            old = prev.get(name)
            if old:
                old = dict(old); old["stale"] = True
                sections[name] = old
                report.append(f"{name}: FAILED ({e}) — kept previous, marked stale")
            else:
                sections[name] = {"fetched_at": None, "stale": True, "items": []}
                report.append(f"{name}: FAILED ({e}) — no previous data")
    prev_items = {k: (v or {}).get("items", []) for k, v in prev.items()}
    new_items = {k: v["items"] for k, v in sections.items()}
    if prev_items == new_items:
        print("Scroll Patrol scan: no content change — files untouched")
        return
    hour_seed = datetime.now(timezone.utc).hour
    quips = {k: QUIPS[k][hour_seed % len(QUIPS[k])] for k in QUIPS}
    wire = {"generated_at": now_iso(), "sections": sections, "quips": quips}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(wire, open(OUT, "w"), indent=1)
    print("Scroll Patrol scan @", now_iso())
    for line in report:
        print(" ", line)
    publish_static(wire)

def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def publish_static(wire):
    import html as H
    s = wire["sections"]; q = wire.get("quips", {})
    gen = wire["generated_at"]
    def card_mw(it):
        return (f'<div class="baked-card"><span class="src">REDDIT · {esc(it.get("sub"))}</span>'
                f'<a href="{esc(it.get("url"))}">{esc(it.get("title"))}</a>'
                f'<span class="meta">▲ {it.get("score", 0)} · {it.get("comments", 0)} comments</span></div>')
    def card_meme(it):
        return (f'<div class="baked-card"><span class="src">MEME · {esc(it.get("sub"))}</span>'
                f'<a href="{esc(it.get("url"))}">{esc(it.get("title"))}</a>'
                f'<span class="meta">▲ {it.get("ups", 0)}</span></div>')
    def card_el(it):
        return (f'<div class="baked-card"><span class="src">{esc(it.get("kind","").upper())}</span>'
                f'<a href="{esc(it.get("url"))}">{esc(it.get("text"))}</a></div>')
    def card_joke(it):
        return (f'<div class="baked-card"><span class="src">{esc(it.get("source","").upper())}</span>'
                f'<p>{esc(it.get("text"))}</p></div>')
    blocks = [f'<p class="baked-updated">Evidence board updated {esc(gen)} UTC — patrolled by '
              f'<a href="https://x.com/bishowppandey">Bishow Pandey</a>. Follow the Chief on X for the live chaos.</p>']
    for key, title, fn in (("most_wanted", "🚨 Most Wanted — trending posts", card_mw),
                           ("meme_stash", "😂 Meme Stash — seized memes", card_meme),
                           ("elsewhere", "🦋 Trending Elsewhere — Bluesky & Lemmy", card_el),
                           ("interrogation", "🤣 The Interrogation Room — jokes under the lamp", card_joke)):
        sec = s.get(key, {})
        blocks.append(f'<section class="baked-sec"><h2>{title}</h2><p class="quip">{esc(q.get(key, ""))}</p>')
        items = sec.get("items") or []
        if items:
            blocks.extend(fn(it) for it in items)
        else:
            blocks.append('<p>Patrol came back empty-handed this hour. The streets are quiet… suspiciously quiet.</p>')
        blocks.append('</section>')
    baked = "\n".join(blocks)
    idx = os.path.join(ROOT, "index.html")
    html = open(idx).read()
    a, b = "<!--WIRE:START-->", "<!--WIRE:END-->"
    if a in html and b in html:
        html = html[:html.index(a) + len(a)] + "\n" + baked + "\n" + html[html.index(b):]
        open(idx, "w").write(html)
    entries = []
    for it in (s.get("most_wanted", {}).get("items") or []):
        entries.append(f'<entry><title>{H.escape(it.get("title", ""))}</title>'
                       f'<link href="{H.escape(it.get("url", ""), quote=True)}"/>'
                       f'<id>{H.escape(it.get("url", ""), quote=True)}</id><updated>{gen}</updated>'
                       f'<summary>Arrested by Scroll Patrol — trending on {H.escape(it.get("sub", ""))}</summary></entry>')
    feed = ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f'<title>Scroll Patrol — trending posts & memes, by Bishow Pandey</title>'
            f'<link href="{SITE}feed.xml" rel="self"/><link href="{SITE}"/>'
            f'<id>{SITE}</id><updated>{gen}</updated>' + "".join(entries) + "</feed>")
    open(os.path.join(ROOT, "feed.xml"), "w").write(feed)
    sm = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          f'<url><loc>{SITE}</loc><lastmod>{gen[:10]}</lastmod><changefreq>hourly</changefreq><priority>1.0</priority></url></urlset>')
    open(os.path.join(ROOT, "sitemap.xml"), "w").write(sm)
    print("  static: index.html baked, feed.xml + sitemap.xml regenerated")

if __name__ == "__main__":
    main()
