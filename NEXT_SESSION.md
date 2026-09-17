# Prompt for a new session — adding Amazon and Fandango

Copy everything in the block below into a new Claude session.

---

I want to extend an existing chart-tracking project to cover Amazon Prime Video
and Fandango. Repo (public): https://github.com/pscanlan23/itunes-chart-monitor
A local clone is at ~/Downloads/itunes_monitor on this Mac.

WHAT EXISTS AND WORKS — don't rebuild it:
- Tracks the film "Nimrods" (iTunes US store, id 6797577735) on Apple's Top
  Movies chart. Currently ~#31 overall, ~#9 in Action & Adventure.
- Runs hourly via GitHub Actions, commits state.json/history.json back to the
  repo so history accumulates.
- Emails on rank change, with per-recipient frequency rules.
- Publishes a self-refreshing dashboard to GitHub Pages.
- Secrets already configured: ITUNES_MONITOR_SMTP_USER, ITUNES_MONITOR_SMTP_PASS,
  ITUNES_MONITOR_RECIPIENTS.

WHAT I WANT: add Amazon Prime Video and Fandango rank tracking alongside Apple,
on the same dashboard and the same alerts.

CRITICAL — START HERE, DO NOT SKIP:
Before writing any code, establish whether a usable public data source actually
exists for Amazon and Fandango. Apple publishes a chart feed; as far as I know
neither of these does. If there isn't a real source, tell me that and stop —
do not build infrastructure on an assumed endpoint. A previous session lost
several hours doing exactly that. If no free source exists, research paid
options (FlixPatrol and similar) and come back with coverage and pricing
before building.

You will need web search for this. If web search is blocked in your
environment, say so immediately rather than working from memory.

ENVIRONMENT GOTCHAS FOUND THE HARD WAY:
- Apple domains (itunes.apple.com, rss.marketingtools.apple.com) are BLOCKED by
  the org egress policy in both the cloud sandbox and the desktop VM. To test
  any Apple call, run it on a GitHub Actions runner or through my Chrome.
- api.github.com is blocked from the cloud sandbox but WORKS from the desktop VM.
- Actions log downloads are blocked (they redirect to a storage host). To see
  what a run did, have the workflow write output to a file and commit it.
- git in the connected folder needs delete permission for its lock files.

APPLE-SPECIFIC FACTS (documented in the README, don't relearn them):
- Use the LEGACY feed: itunes.apple.com/us/rss/topmovies/limit=100/json
  The newer rss.marketingtools.apple.com API 404s for movies — it serves only
  Music, Podcasts, Apps, Books, Audio Books.
- The feed EXCLUDES Movie Bundles; the Apple TV app counts them. So our rank
  reads lower than the app's (#32 here was #45 there). The dashboard says so.
- Store IDs differ per storefront — the same film has different ids in US and CA.
- The iTunes Search API returns 0 results for these titles. It is useless for
  resolution; match against the chart feed instead.

Ask me before making structural changes. I'd rather be asked than surprised.
