#!/usr/bin/env python3
"""
iTunes chart position monitor.

Tracks one or more films' rank on Apple's public "Top Movies" chart feed,
emails the configured recipients whenever a tracked film's position changes
(including entering or dropping off the chart), and regenerates a static
HTML dashboard showing current position + recent history for each film.

Designed to be run on a schedule (cron, Claude Code scheduled job, etc.) —
each run is a single check-compare-notify-render pass. No persistent
process is required or created by this script.

Usage:
    python3 monitor.py                # normal run
    python3 monitor.py --dry-run      # fetch + compare, but skip sending email
    python3 monitor.py --resolve-only # just print iTunes search matches for
                                       # each film in config.json, to help you
                                       # pick the right itunes_id and lock it in

Requires: requests  (pip install requests --break-system-packages)
Email requires two env vars set (names configurable in config.json):
    ITUNES_MONITOR_SMTP_USER
    ITUNES_MONITOR_SMTP_PASS
"""

import argparse
import json
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SEARCH_API = "https://itunes.apple.com/search"
CHART_FEED_TMPL = (
    "https://rss.marketingtools.apple.com/api/v2/{storefront}/movies/{chart}/{limit}/movies.json"
)


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


def resolve_film(film, storefront):
    """
    Return the best-guess iTunes listing for a film config entry.
    If itunes_id is set in config, that's authoritative and we skip search.
    Otherwise we search by title and return the top candidate(s) so the
    caller (or --resolve-only) can disambiguate.
    """
    if film.get("itunes_id"):
        return {"id": str(film["itunes_id"]), "name": film["name"], "matched_by": "itunes_id"}

    params = {
        "term": film["search_term"],
        "country": storefront,
        "entity": "movie",
        "limit": 10,
    }
    resp = requests.get(SEARCH_API, params=params, timeout=15)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None

    # Prefer an exact (case-insensitive) title match; otherwise take the first hit.
    exact = [r for r in results if r.get("trackName", "").strip().lower() == film["search_term"].strip().lower()]
    best = exact[0] if exact else results[0]
    return {
        "id": str(best.get("trackId")),
        "name": best.get("trackName"),
        "artist": best.get("artistName"),
        "url": best.get("trackViewUrl"),
        "matched_by": "exact_search" if exact else "fuzzy_search",
        "all_candidates": results,
    }


def fetch_chart(storefront, chart, limit):
    url = CHART_FEED_TMPL.format(storefront=storefront, chart=chart, limit=limit)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json().get("feed", {}).get("results", [])


def find_rank(chart_results, film_id, film_name):
    """
    Return 1-based rank of the film in the chart, matching by id first,
    falling back to case-insensitive name match. None if not present.
    """
    for idx, entry in enumerate(chart_results):
        if film_id and str(entry.get("id")) == str(film_id):
            return idx + 1
    for idx, entry in enumerate(chart_results):
        if entry.get("name", "").strip().lower() == film_name.strip().lower():
            return idx + 1
    return None


def send_email(cfg, subject, body):
    email_cfg = cfg["email"]
    if not email_cfg.get("enabled", True):
        print(f"[email disabled] {subject}")
        return
    user = os.environ.get(email_cfg["smtp_user_env"])
    password = os.environ.get(email_cfg["smtp_pass_env"])
    if not user or not password:
        print(
            f"[email skipped] Missing {email_cfg['smtp_user_env']} / "
            f"{email_cfg['smtp_pass_env']} environment variables."
        )
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
    films_html = []
    for name, s in state.items():
        rank = s.get("rank")
        rank_display = f"#{rank}" if rank else "Not on chart"
        checked = s.get("last_checked", "—")
        hist = history.get(name, [])[-20:]  # last 20 checks
        rows = "".join(
            f"<tr><td>{h['timestamp']}</td><td>{'#' + str(h['rank']) if h['rank'] else '—'}</td></tr>"
            for h in reversed(hist)
        )
        films_html.append(f"""
        <div class="card">
          <h2>{name}</h2>
          <div class="current-rank">{rank_display}</div>
          <div class="last-checked">Last checked: {checked}</div>
          <details>
            <summary>Recent history</summary>
            <table>
              <thead><tr><th>Checked</th><th>Rank</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </details>
        </div>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>iTunes Chart Monitor</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #f5f5f7; margin: 0; padding: 2rem; color: #1d1d1f; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 1.5rem; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
  .card {{ background: white; border-radius: 12px; padding: 1.25rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 220px; }}
  .card h2 {{ font-size: 1.1rem; margin: 0 0 0.5rem; }}
  .current-rank {{ font-size: 2rem; font-weight: 600; color: #0071e3; }}
  .last-checked {{ font-size: 0.8rem; color: #6e6e73; margin-top: 0.25rem; }}
  details {{ margin-top: 0.75rem; font-size: 0.85rem; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; }}
  th, td {{ text-align: left; padding: 0.2rem 0.4rem; border-bottom: 1px solid #eee; }}
  footer {{ margin-top: 2rem; font-size: 0.75rem; color: #a1a1a6; }}
</style>
</head>
<body>
  <h1>iTunes Movie Chart Monitor — {cfg.get('chart', 'top-movies')} ({cfg.get('storefront', 'us').upper()})</h1>
  <div class="grid">
    {''.join(films_html)}
  </div>
  <footer>Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · rechecks each time this script runs on schedule</footer>
</body>
</html>
"""
    dashboard_path = HERE / cfg["dashboard_path"]
    dashboard_path.write_text(html)
    return dashboard_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Check and render, but don't send email")
    parser.add_argument("--resolve-only", action="store_true", help="Print search matches for each film and exit")
    parser.add_argument("--inspect-chart", action="store_true",
                        help="Dump the first few raw chart entries, to confirm the feed exists "
                             "and see what ID format it uses for matching")
    args = parser.parse_args()

    cfg = load_json(HERE / "config.json", None)
    if cfg is None:
        print("config.json not found next to monitor.py", file=sys.stderr)
        sys.exit(1)

    if args.inspect_chart:
        url = CHART_FEED_TMPL.format(
            storefront=cfg["storefront"], chart=cfg["chart"], limit=cfg["chart_limit"]
        )
        print(f"Feed: {url}\n")
        results = fetch_chart(cfg["storefront"], cfg["chart"], cfg["chart_limit"])
        print(f"Entries returned: {len(results)}\n")
        print("First 3 entries verbatim (check the shape of the 'id' field — the\n"
              "value in config.json's itunes_id must match this format exactly):\n")
        print(json.dumps(results[:3], indent=2))
        return

    if args.resolve_only:
        for film in cfg["films"]:
            match = resolve_film(film, cfg["storefront"])
            print(f"\n=== {film['name']} ===")
            print(json.dumps(match, indent=2))
        return

    state = load_json(cfg["state_path"], {})
    history = load_json(cfg["history_path"], {})

    chart_results = fetch_chart(cfg["storefront"], cfg["chart"], cfg["chart_limit"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for film in cfg["films"]:
        name = film["name"]
        resolved = resolve_film(film, cfg["storefront"])
        film_id = resolved["id"] if resolved else None

        new_rank = find_rank(chart_results, film_id, name)
        prev = state.get(name, {})
        old_rank = prev.get("rank")

        state[name] = {"rank": new_rank, "last_checked": now, "resolved_id": film_id}
        history.setdefault(name, []).append({"timestamp": now, "rank": new_rank})

        if new_rank != old_rank:
            if old_rank is None and new_rank is not None:
                subject = f"{name} just entered the iTunes chart at #{new_rank}"
                body = f"{name} appeared on the {cfg['chart']} chart at position #{new_rank} as of {now}."
            elif old_rank is not None and new_rank is None:
                subject = f"{name} dropped off the iTunes chart"
                body = f"{name} was at #{old_rank} and is no longer in the top {cfg['chart_limit']} as of {now}."
            else:
                direction = "up" if new_rank < old_rank else "down"
                subject = f"{name} moved {direction} on iTunes: #{old_rank} -> #{new_rank}"
                body = f"{name} moved from #{old_rank} to #{new_rank} on the {cfg['chart']} chart as of {now}."

            print(subject)
            if not args.dry_run:
                send_email(cfg, subject, body)
        else:
            print(f"{name}: no change (#{new_rank if new_rank else 'off chart'})")

    # Keep history bounded. It's committed to git on every run, so without a cap
    # it grows forever. 2000 entries per film is ~83 days at hourly checks.
    limit = cfg.get("history_limit")
    if limit:
        for film_name in history:
            history[film_name] = history[film_name][-limit:]

    save_json(cfg["state_path"], state)
    save_json(cfg["history_path"], history)
    dashboard_path = render_dashboard(cfg, state, history)
    print(f"Dashboard written to {dashboard_path}")


if __name__ == "__main__":
    main()
