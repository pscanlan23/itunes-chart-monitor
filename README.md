# iTunes Chart Monitor

Tracks a film's rank on Apple's public "Top Movies" chart, emails you when the
position changes, and publishes a dashboard to GitHub Pages.

Runs entirely on GitHub Actions — nothing needs to stay running on your machine.

Currently tracking: **Nimrods**

---

## Tonight: get it live in ~15 minutes

You do **not** need the iTunes ID or the email credentials to launch. Both can
be added later without touching anything else. Do only this:

1. **Push the repo.** Create a public repo on GitHub, then:
   ```bash
   git init && git add . && git commit -m "iTunes chart monitor"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
2. **Turn on Pages.** Settings → Pages → Deploy from a branch → `main` / `/ (root)`.
3. **Run it.** Actions tab → *iTunes chart check* → Run workflow.

That's it — the dashboard is live at `https://<you>.github.io/<repo>/` and
rechecks hourly from then on.

**Why no ID needed:** the script resolves "Nimrods" by title on each run and
writes what it found to `state.json` as `resolved_id`. Since `state.json` is
committed back to the repo, after the first run you can just read the ID out of
it. The system tells you the answer instead of you having to look it up.

**Why no email needed:** with the secrets unset, the script logs
`[email skipped]` and carries on normally. The dashboard still updates. Add the
credentials whenever you get to it and alerts start flowing.

Then, at your leisure: [lock in the ID](#4-lock-in-the-itunes-id) and
[set up email](#2-generate-a-gmail-app-password).

---

## Full setup

### 1. Create the repo and push these files

Create a new **public** repo on GitHub (public is required for free GitHub
Pages), then from this folder:

```bash
git init
git add .
git commit -m "iTunes chart monitor"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### 2. Generate a Gmail App Password

The monitor sends mail through `smtp.gmail.com` as `paul@legionm.com`. Google
will not accept your normal password for SMTP — you need a 16-character App
Password.

**Prerequisite:** 2-Step Verification must be on for the account. Check at
[myaccount.google.com/signinoptions/twosv](https://myaccount.google.com/signinoptions/twosv).
If it's off, turn it on first — the App Passwords page won't exist otherwise.

Then:

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   (signed in as `paul@legionm.com`).
2. Type a name — `iTunes Chart Monitor` — and click **Create**.
3. Copy the 16-character password it shows you. **Spaces don't matter**; Google
   displays it in groups of four for readability. You only see it once.

**If that page says the setting isn't available:** `legionm.com` is a Google
Workspace domain, and your admin has App Passwords disabled org-wide. Two ways
forward — tell me which and I'll adjust `config.json`:

- Ask your Workspace admin to enable "Allow users to create app passwords"
  (Admin console → Security → Authentication → Less secure apps / App passwords).
- Or switch to a transactional sender like SendGrid or Mailgun, which is the
  more robust option anyway and doesn't depend on a personal account.

### 3. Add the two secrets to the repo

In the repo: **Settings → Secrets and variables → Actions → New repository secret.**

| Name | Value |
|---|---|
| `ITUNES_MONITOR_SMTP_USER` | `paul@legionm.com` |
| `ITUNES_MONITOR_SMTP_PASS` | the 16-character App Password |

These are encrypted, are not readable back out of the UI, and are not exposed to
pull requests from forks. **Don't put them in `config.json`** — that file is
public in this repo.

### 4. Lock in the iTunes ID (already done for Nimrods: 6797577735)

After the first successful run, open `state.json` in the repo. It contains what
the title search resolved to:

```json
{ "Nimrods": { "rank": null, "last_checked": "...", "resolved_id": "6797577735" } }
```

Sanity-check that ID against the film's Apple TV page, or run **Actions →
Resolve iTunes IDs** for the full match details (title, artist, store URL).
Then set it in `config.json`:

```json
{ "name": "Nimrods", "search_term": "Nimrods", "itunes_id": 1234567890 }
```

This matters more than it looks. Until `itunes_id` is set, every run falls back
to fuzzy title matching, and a different film with the same name would produce a
false rank. Once it's set, matching is exact and the search API isn't called at
all.

### 5. Turn on GitHub Pages

**Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)` → Save.**

The dashboard lands at `https://<you>.github.io/<repo>/`. The hourly job copies
`dashboard.html` to `index.html` and pushes, so the page refreshes itself after
every check.

Note this is a public URL — the dashboard and the full rank history are visible
to anyone who has the link.

### 6. Confirm it works

Actions tab → **iTunes chart check** → **Run workflow**. That does a real check
immediately rather than waiting for the hour. First run always emails, since
every film goes from "unknown" to a known state.

---

## Adding another film (e.g. Coyote)

Add an entry to `films` in `config.json`:

```json
{ "name": "Coyote", "search_term": "Coyote", "itunes_id": null }
```

Then run **Resolve iTunes IDs** and lock in the id, same as step 4. Worth doing
only once the film is actually live on iTunes — a generic title like "Coyote"
will otherwise fuzzy-match something unrelated.

---

## How it runs

`.github/workflows/monitor.yml` fires hourly at :17, checks the chart, emails on
any change, regenerates the dashboard, and commits `state.json`, `history.json`,
and `dashboard.html` back to `main`.

Committing state is what makes history accumulate — the runner is a fresh
machine every time, so anything not committed is gone.

**Scheduling caveat:** GitHub's cron is best-effort. Runs commonly land 5–20
minutes late and are occasionally skipped entirely under platform load. Fine for
chart tracking; don't treat the timestamps as precise. (GitHub also disables
scheduled workflows in repos with no activity for 60 days — the hourly commits
keep this one alive automatically.)

A failed run — Apple's API down, bad credentials — shows as a red X in the
Actions tab, and GitHub emails you about it by default.

## Files

| File | |
|---|---|
| `monitor.py` | the check/compare/notify/render script |
| `config.json` | films tracked, chart settings, email settings — **public** |
| `requirements.txt` | Python deps |
| `.github/workflows/monitor.yml` | hourly job |
| `.github/workflows/resolve.yml` | manual iTunes ID lookup |
| `state.json` | auto-created; last known rank per film |
| `history.json` | auto-created; rolling log, capped at 2000 entries per film |
| `dashboard.html` / `index.html` | auto-generated each run |

## Running locally

```bash
pip install -r requirements.txt
python3 monitor.py --resolve-only   # print iTunes matches, change nothing
python3 monitor.py --dry-run        # check and render, but don't email
```

## Data source

Chart data comes from the legacy iTunes RSS feed:

```
https://itunes.apple.com/us/rss/topmovies/limit=100/json
```

Apple's newer `rss.marketingtools.apple.com` JSON API does **not** serve movie
charts — it 404s on every limit, and its own generator lists only Music,
Podcasts, Apps, Books and Audio Books. Use the legacy feed above.

The chart runs about 78 entries deep; `limit=100` asks for all of them.

Note the iTunes **Search** API is not usable for resolving these films — it
returns 0 results even for titles that are live and charting. `--resolve-only`
matches against the chart feed instead.

## Email alerts

Who gets told, and how often, is set per recipient in `config.json`:

```json
"recipients": [
  { "address": "paul@legionm.com",  "alerts": "every_change" },
  { "address": "team@legionm.com",  "alerts": "significant", "min_move": 5 },
  { "address": "board@legionm.com", "alerts": "milestones" },
  { "address": "someone@legionm.com", "alerts": "none" }
]
```

| Mode | Sends when |
|---|---|
| `every_change` | any movement at all, including #31 to #32 |
| `significant` | the rank moves by `min_move` places or more (default 5) |
| `milestones` | the film crosses into or out of the top 5, 10, 25 or 50 |
| `none` | never — mutes an address without removing it |

**Entering or dropping off the chart always sends**, whatever the mode, except
for `none`. Those are the events nobody wants to miss.

One email goes out per change, addressed to everyone whose rule matched, so
nobody gets a duplicate. The body carries the current overall and genre rank,
both previous values, price, release date, Apple's feed timestamp, and links to
the store page and dashboard.

To verify the SMTP secrets without waiting for the chart to move, run the
**Send test email** workflow from the Actions tab. It fails the run if the mail
does not go out, so a green check means it genuinely sent.
