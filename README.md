# slayyyter-tickets

Resale price monitor for **Slayyyter @ The Regency Ballroom — Tue Sep 8 2026, 8pm PT**.

Alerts when the all-in resale price drops to **$170 or below**, with secondary
alerts on big trend drops and a last-48h backstop so you don't strand waiting
for an aggressive threshold. Runs unattended for ~4 months on GitHub Actions
free tier. **$0/month.**

See [PLAN.md context](#plan) for the full design (in `/Users/phillipchaffee/.claude/plans/`).

## What it does

- Polls Ticketmaster Discovery API + SeatGeek Platform API on a date-aware schedule
  (every 6h now → every 15min on show day).
- Logs every price snapshot to `data/prices.ndjson` (committed to this repo —
  free version-controlled history; also keeps the repo "active" so GitHub
  doesn't auto-disable scheduled workflows).
- Evaluates 8 alert rules: threshold, 24h drop, 7d trend, last-48h backstop,
  Aug 1/Aug 20 mid-campaign check-ins, daily heartbeat, inventory-drying,
  with separate "pair likely" vs "single only" alerts based on listing count.
- Sends alerts via **ntfy.sh** (push) and **SMTP** (email backup).

## Quick reference

| Action | How |
|---|---|
| First-time setup | See `SETUP.md` |
| Trigger a poll manually | GitHub → Actions → "poll" → Run workflow |
| Force a poll even if not due | Same, with "Poll even if not due" checked |
| See current floor | `data/latest.json` |
| See full history | `data/prices.ndjson` (one JSON object per line) |
| Revise threshold mid-campaign | edit `config.yaml` → push |
| Pause all alerts | set `paused: true` in `config.yaml` → push |
| Disable workflow | rename `.github/workflows/poll.yml` → `poll.yml.disabled` and push |
| Run locally | `.venv/bin/python -m monitor.poll --dry-run -v` |
| Run tests | `.venv/bin/pytest -v` |

## Local dev

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                      # 34 tests
.venv/bin/python -m monitor.poll --dry-run -v
```

## Calendar

| Date | Cadence | Notable |
|---|---|---|
| **May 6 → Jul 31** | every 6h | Idle baseline. Daily heartbeat at 9am PT. |
| **Aug 1** | — | Mid-campaign check-in #1. Decide: keep $170 or revise. |
| **Aug 1 → Aug 8** | every 2h | Pre-unlock ramp. |
| **Aug 9** | every 15min | **Transfer lock lifts.** Big inflection. |
| **Aug 10 → Aug 19** | every hour | Steady-state. |
| **Aug 20** | — | Mid-campaign check-in #2. |
| **Aug 21 → Aug 31** | every hour | Steady-state. |
| **Sep 1 → Sep 7** | every 30min | Buy window. |
| **Sep 6 → Sep 8** | — | Backstop alerts at 9am + 5pm PT. |
| **Sep 8** | every 15min | Show day. |
