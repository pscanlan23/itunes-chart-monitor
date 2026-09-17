#!/usr/bin/env python3
"""
iTunes chart position monitor.

Tracks films on Apple's US "Top Movies" chart, emails when a position changes,
and regenerates a static HTML dashboard.

IMPORTANT NOTES ON THE DATA SOURCE (learned the hard way):

  * Apple's newer rss.marketingtools.apple.com JSON API does NOT serve movie
    charts -- it 404s at every limit, and its own generator offers only Music,
    Podcasts, Apps, Books and Audio Books. The LEGACY iTunes RSS feed used
    below is the one that carries movies.

  * The feed EXCLUDES Movie Bundles, which the Apple TV app includes when it
    numbers its chart. So our rank is "rank among individual films" and will
    read LOWER (better) than the number shown in the app. Observed 2026-09-17:
    feed #32 vs app #45, with 13 bundles in between. This is a real difference
    in what is being counted, not a bug -- the dashboard says so explicitly.

  * Store IDs are PER-STOREFRONT. The same film can have a different id in the
    US and CA stores (Tony: US 6802507831 / CA 6807226367). Never reuse an id
    across storefronts -- resolve each storefront separately or it will report
    "not on chart" forever.

  * The iTunes SEARCH API is useless here: it returns 0 results even for films
    that are live and charting. Resolution is done against the chart feed.

Usage:
    python3 monitor.py                # normal run
    python3 monitor.py --dry-run      # fetch + compare, but skip sending email
    python3 monitor.py --resolve-only # print chart matches for each film
    python3 monitor.py --inspect-chart# dump raw feed shape

Requires: requests
Email requires two env vars (names configurable in config.json):
    ITUNES_MONITOR_SMTP_USER
    ITUNES_MONITOR_SMTP_PASS
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CHART_FEED_TMPL = "https://itunes.apple.com/{storefront}/rss/{chart}/limit={limit}/json"
GENRE_FEED_TMPL = "https://itunes.apple.com/{storefront}/rss/{chart}/limit={limit}/genre={genre}/json"


def load_json(path, default):
    p = Path(path)
    if not p.is_absolute():
        p = HERE / p
    if not p.exists():
        return default
    with open(p, "r") as f:
        return json.load(f)


def save_json(path, data):
    p = Path(path)
    if not p.is_absolute():
        p = HERE / p
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


def _normalise(e):
    """Flatten one deeply-nested legacy RSS entry into something usable."""
    cat = (e.get("category") or {}).get("attributes", {})
    images = e.get("im:image") or []
    return {
        "id": str(e["id"]["attributes"]["im:id"]),
        "name": e["im:name"]["label"],
        "url": e["id"]["label"],
        "genre": cat.get("label"),
        "genre_id": cat.get("im:id"),
        "artist": (e.get("im:artist") or {}).get("label"),
        "price": (e.get("im:price") or {}).get("label"),
        "rental_price": (e.get("im:rentalPrice") or {}).get("label"),
        "release_date": ((e.get("im:releaseDate") or {}).get("attributes") or {}).get("label"),
        "artwork": (images[-1].get("label") if images else None),
    }


def fetch_chart(storefront, chart, limit, genre=None):
    """
    Fetch a chart and return {"entries": [...ranked...], "updated": <str|None>}.

    `updated` is Apple's own rebuild timestamp for the feed -- worth surfacing,
    since our check time and Apple's refresh time are not the same thing.
    """
    tmpl = GENRE_FEED_TMPL if genre else CHART_FEED_TMPL
    url = tmpl.format(storefront=storefront, chart=chart, limit=limit, genre=genre)
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    feed = resp.json().get("feed", {})
    entries = []
    for e in feed.get("entry", []) or []:
        try:
            entries.append(_normalise(e))
        except (KeyError, TypeError):
            continue  # skip a malformed row rather than failing the whole run
    return {"entries": entries, "updated": (feed.get("updated") or {}).get("label")}


def find_rank(entries, film_id, film_name):
    """1-based position in the list; id first, then case-insensitive name."""
    for idx, e in enumerate(entries):
        if film_id and str(e.get("id")) == str(film_id):
            return idx + 1
    for idx, e in enumerate(entries):
        if (e.get("name") or "").strip().lower() == film_name.strip().lower():
            return idx + 1
    return None


def resolve_film(film, storefront, entries=None):
    """itunes_id wins; otherwise match by name against the chart itself."""
    if film.get("itunes_id"):
        return {"id": str(film["itunes_id"]), "name": film["name"], "matched_by": "itunes_id"}
    term = (film.get("search_term") or film["name"]).strip().lower()
    for e in (entries or []):
        if (e.get("name") or "").strip().lower() == term:
            return {**e, "matched_by": "chart_exact"}
    for e in (entries or []):
        if term in (e.get("name") or "").strip().lower():
            return {**e, "matched_by": "chart_partial"}
    return None


def send_email(cfg, subject, body):
    email_cfg = cfg["email"]
    if not email_cfg.get("enabled", True):
        print(f"[email disabled] {subject}")
        return
    user = os.environ.get(email_cfg["smtp_user_env"])
    password = os.environ.get(email_cfg["smtp_pass_env"])
    if not user or not password:
        print(f"[email skipped] Missing {email_cfg['smtp_user_env']} / "
              f"{email_cfg['smtp_pass_env']} environment variables.")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = email_cfg.get("from") or user
    msg["To"] = ", ".join(email_cfg["to"])
    with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(msg["From"], email_cfg["to"], msg.as_string())
    print(f"[email sent] {subject}")


def render_dashboard(cfg, state, history):
    cards = []
    for name, s in state.items():
        rank = s.get("rank")
        grank = s.get("genre_rank")
        genre = s.get("genre")
        art = s.get("artwork")

        rank_display = f"#{rank}" if rank else "Not on chart"
        rank_class = "rank" if rank else "rank off"

        genre_block = ""
        if genre:
            gtxt = f"#{grank}" if grank else "—"
            genre_block = (f'<div class="tile"><div class="tile-v">{escape(gtxt)}</div>'
                           f'<div class="tile-k">in {escape(genre)}</div></div>')

        meta = []
        if s.get("price"):
            meta.append(("Buy", s["price"]))
        if s.get("rental_price"):
            meta.append(("Rent", s["rental_price"]))
        if s.get("release_date"):
            meta.append(("Released", s["release_date"]))
        meta_html = "".join(
            f'<div class="m"><span class="mk">{escape(k)}</span>'
            f'<span class="mv">{escape(str(v))}</span></div>' for k, v in meta)

        hist = history.get(name, [])[-30:]
        rows = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                escape(h.get("timestamp", "")),
                ("#" + str(h["rank"])) if h.get("rank") else "—",
                ("#" + str(h["genre_rank"])) if h.get("genre_rank") else "—",
            ) for h in reversed(hist))

        art_html = (f'<img class="art" src="{escape(art)}" alt="" width="113" height="170">'
                    if art else "")
        link = s.get("url")
        title_html = (f'<a href="{escape(link)}">{escape(name)}</a>' if link else escape(name))

        cards.append(f"""
      <section class="card">
        <div class="head">
          {art_html}
          <div class="headtext">
            <h2>{title_html}</h2>
            <div class="{rank_class}">{escape(rank_display)}</div>
            <div class="sub">among individual films · US store</div>
          </div>
          {genre_block}
        </div>
        <div class="meta">{meta_html}</div>
        <details>
          <summary>History ({len(history.get(name, []))} checks)</summary>
          <table>
            <thead><tr><th>Checked</th><th>Overall</th><th>Genre</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </details>
      </section>""")

    feed_updated = next((s.get("feed_updated") for s in state.values() if s.get("feed_updated")), None)
    checked = next((s.get("last_checked") for s in state.values() if s.get("last_checked")), None)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>iTunes Chart Monitor</title>
<style>
  :root {{
    --bg:#f5f5f7; --surface:#fff; --ink:#1d1d1f; --ink2:#4a4a4f; --muted:#86868b;
    --line:#e3e3e6; --accent:#0058a8; --off:#86868b;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg:#111113; --surface:#1c1c1f; --ink:#f2f2f4; --ink2:#c4c4ca; --muted:#8a8a91;
      --line:#2c2c31; --accent:#6ba6ff; --off:#8a8a91;
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--ink); margin:0; padding:24px 16px 48px; }}
  .wrap {{ max-width:760px; margin:0 auto; }}
  h1 {{ font-size:1.05rem; font-weight:600; letter-spacing:.01em; margin:0 0 4px; }}
  .lede {{ color:var(--muted); font-size:.82rem; margin:0 0 22px; line-height:1.5; }}
  .card {{ background:var(--surface); border:1px solid var(--line); border-radius:14px;
           padding:20px; margin-bottom:16px; }}
  .head {{ display:flex; gap:16px; align-items:flex-start; }}
  .art {{ border-radius:8px; flex:none; background:var(--line); }}
  .headtext {{ flex:1; min-width:0; }}
  h2 {{ font-size:1rem; font-weight:600; margin:0 0 6px; }}
  h2 a {{ color:inherit; text-decoration:none; }}
  h2 a:hover {{ text-decoration:underline; }}
  .rank {{ font-size:2.6rem; font-weight:650; line-height:1; color:var(--accent);
           font-variant-numeric:tabular-nums; }}
  .rank.off {{ font-size:1.1rem; font-weight:500; color:var(--off); }}
  .sub {{ font-size:.75rem; color:var(--muted); margin-top:5px; }}
  .tile {{ flex:none; text-align:right; }}
  .tile-v {{ font-size:1.5rem; font-weight:600; color:var(--ink2);
             font-variant-numeric:tabular-nums; line-height:1; }}
  .tile-k {{ font-size:.72rem; color:var(--muted); margin-top:4px; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:18px; margin-top:16px;
           padding-top:14px; border-top:1px solid var(--line); }}
  .m {{ display:flex; flex-direction:column; gap:2px; }}
  .mk {{ font-size:.68rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
  .mv {{ font-size:.85rem; color:var(--ink2); font-variant-numeric:tabular-nums; }}
  details {{ margin-top:14px; font-size:.82rem; }}
  summary {{ cursor:pointer; color:var(--muted); }}
  table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
  th,td {{ text-align:left; padding:5px 6px; border-bottom:1px solid var(--line);
           font-variant-numeric:tabular-nums; }}
  th {{ font-size:.68rem; text-transform:uppercase; letter-spacing:.06em;
        color:var(--muted); font-weight:500; }}
  td {{ color:var(--ink2); }}
  .note {{ background:var(--surface); border:1px solid var(--line); border-radius:14px;
           padding:16px 20px; font-size:.79rem; color:var(--ink2); line-height:1.6; }}
  .note b {{ color:var(--ink); font-weight:600; }}
  footer {{ margin-top:20px; font-size:.72rem; color:var(--muted); line-height:1.6; }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>iTunes Top Movies — US</h1>
    <p class="lede">Chart position, rechecked hourly.</p>
    {''.join(cards)}
    <div class="note">
      <b>Why this differs from the Apple TV app.</b> Apple's chart feed lists only
      individual films. The app's numbering also counts Movie Bundles, so the
      position shown there is higher than the one here — on 17 Sep, #32 here was
      #45 in the app, with 13 bundles in between. Neither is wrong; they count
      different things. The number above is rank among films.
    </div>
    <footer>
      Checked {escape(checked or '—')} · Apple's feed last rebuilt {escape(feed_updated or '—')}<br>
      Source: itunes.apple.com/us/rss/topmovies · chart runs ~78 films deep
    </footer>
  </div>
</body>
</html>
"""
    dashboard_path = HERE / cfg["dashboard_path"]
    dashboard_path.write_text(html)
    return dashboard_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Check and render, but don't send email")
    parser.add_argument("--resolve-only", action="store_true", help="Print chart matches and exit")
    parser.add_argument("--inspect-chart", action="store_true", help="Dump raw feed shape")
    args = parser.parse_args()

    cfg = load_json(HERE / "config.json", None)
    if cfg is None:
        print("config.json not found next to monitor.py", file=sys.stderr)
        sys.exit(1)

    sf, ch, lim = cfg["storefront"], cfg["chart"], cfg["chart_limit"]

    if args.inspect_chart:
        chart = fetch_chart(sf, ch, lim)
        print(f"Feed: {CHART_FEED_TMPL.format(storefront=sf, chart=ch, limit=lim)}")
        print(f"Apple rebuilt the feed at: {chart['updated']}")
        print(f"Entries: {len(chart['entries'])}\n")
        print(json.dumps(chart["entries"][:3], indent=2))
        return

    if args.resolve_only:
        chart = fetch_chart(sf, ch, lim)
        print(f"Chart has {len(chart['entries'])} entries (rebuilt {chart['updated']}).\n")
        for film in cfg["films"]:
            print(f"=== {film['name']} ===")
            print(json.dumps(resolve_film(film, sf, chart["entries"]), indent=2))
        return

    state = load_json(cfg["state_path"], {})
    history = load_json(cfg["history_path"], {})

    chart = fetch_chart(sf, ch, lim)
    entries = chart["entries"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    genre_cache = {}

    for film in cfg["films"]:
        name = film["name"]
        resolved = resolve_film(film, sf, entries)
        film_id = resolved["id"] if resolved else None

        new_rank = find_rank(entries, film_id, name)
        entry = next((e for e in entries if film_id and e["id"] == str(film_id)), None)

        genre_rank = None
        genre = entry.get("genre") if entry else None
        gid = entry.get("genre_id") if entry else None
        if gid:
            if gid not in genre_cache:
                try:
                    genre_cache[gid] = fetch_chart(sf, ch, lim, genre=gid)["entries"]
                except Exception as exc:          # a genre feed failing must not kill the run
                    print(f"[warn] genre feed {gid} failed: {exc}")
                    genre_cache[gid] = []
            genre_rank = find_rank(genre_cache[gid], film_id, name)

        prev = state.get(name, {})
        old_rank, old_grank = prev.get("rank"), prev.get("genre_rank")

        state[name] = {
            "rank": new_rank,
            "genre_rank": genre_rank,
            "genre": genre or prev.get("genre"),
            "last_checked": now,
            "feed_updated": chart["updated"],
            "resolved_id": film_id,
            "url": (entry or {}).get("url") or prev.get("url"),
            "artwork": (entry or {}).get("artwork") or prev.get("artwork"),
            "price": (entry or {}).get("price") or prev.get("price"),
            "rental_price": (entry or {}).get("rental_price") or prev.get("rental_price"),
            "release_date": (entry or {}).get("release_date") or prev.get("release_date"),
            "artist": (entry or {}).get("artist") or prev.get("artist"),
        }
        history.setdefault(name, []).append(
            {"timestamp": now, "rank": new_rank, "genre_rank": genre_rank})

        gtxt = f" (#{genre_rank} in {genre})" if genre_rank and genre else ""
        if new_rank != old_rank:
            if old_rank is None and new_rank is not None:
                subject = f"{name} entered the iTunes chart at #{new_rank}"
                body = f"{name} appeared at #{new_rank} among individual films{gtxt} as of {now}."
            elif old_rank is not None and new_rank is None:
                subject = f"{name} dropped off the iTunes chart"
                body = f"{name} was #{old_rank} and is no longer listed as of {now}."
            else:
                direction = "up" if new_rank < old_rank else "down"
                subject = f"{name} moved {direction} on iTunes: #{old_rank} -> #{new_rank}"
                body = f"{name} moved from #{old_rank} to #{new_rank}{gtxt} as of {now}."
            body += ("\n\nNote: this is rank among individual films. The Apple TV app "
                     "numbers its chart with Movie Bundles included, so the position "
                     "shown there will be higher.")
            print(subject)
            if not args.dry_run:
                send_email(cfg, subject, body)
        else:
            shown = f"#{new_rank}" if new_rank else "off chart"
            extra = "" if genre_rank == old_grank else f" [genre {old_grank} -> {genre_rank}]"
            print(f"{name}: no change ({shown}{gtxt}){extra}")

    limit = cfg.get("history_limit")
    if limit:
        for film_name in history:
            history[film_name] = history[film_name][-limit:]

    save_json(cfg["state_path"], state)
    save_json(cfg["history_path"], history)
    print(f"Dashboard written to {render_dashboard(cfg, state, history)}")


if __name__ == "__main__":
    main()
