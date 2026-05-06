# Setup

One-time setup — should take ~20 minutes.

## 1. Get API keys

### Ticketmaster Developer

1. Go to <https://developer.ticketmaster.com> → Sign up.
2. Create a new app. Copy the **Consumer Key** (this is your `TICKETMASTER_API_KEY`).
3. Test it:
   ```sh
   curl "https://app.ticketmaster.com/discovery/v2/events.json?keyword=Slayyyter&apikey=YOUR_KEY"
   ```
4. Free tier: 5,000 calls/day, 5/sec. Way more than we need.

### SeatGeek Platform

1. Go to <https://seatgeek.com/build> → Sign up.
2. Create an app. Copy `client_id` and `client_secret`.
3. Test:
   ```sh
   curl "https://api.seatgeek.com/2/events?q=Slayyyter&client_id=YOUR_ID"
   ```

## 2. Set up notifications

### ntfy.sh (primary push channel)

1. Generate a hard-to-guess topic name (topics are public — guess = others read your alerts):
   ```sh
   python3 -c "import secrets; print(secrets.token_urlsafe(16))"
   ```
2. Install the ntfy app:
   - iOS: <https://apps.apple.com/us/app/ntfy/id1625396347>
   - Android: <https://play.google.com/store/apps/details?id=io.heckel.ntfy>
3. In the app, subscribe to your topic name (no signup needed).
4. Test:
   ```sh
   curl -d "hello" "https://ntfy.sh/YOUR_TOPIC"
   ```
   You should see a notification in seconds.

### Gmail SMTP (optional — email backup channel)

**Skip this if you're happy with ntfy alone.** notify.py auto-skips SMTP when the secrets aren't set.

If you want it:
1. Make sure you have 2FA enabled on your Google account.
2. Go to <https://myaccount.google.com/apppasswords>.
3. Create an app password (label "slayyyter-tickets"). Copy the 16-char password.
4. Test it locally before adding to GitHub:
   ```sh
   python3 -c "
   import smtplib
   from email.message import EmailMessage
   m = EmailMessage()
   m['Subject'] = 'test'
   m['From'] = 'YOUR_GMAIL@gmail.com'
   m['To'] = 'phillipdensmorechaffee@gmail.com'
   m.set_content('test')
   with smtplib.SMTP('smtp.gmail.com', 587) as s:
       s.starttls(); s.login('YOUR_GMAIL@gmail.com', 'APP_PASSWORD'); s.send_message(m)
   "
   ```

## 3. Create the GitHub repo

1. Make a **public** repo named `slayyyter-tickets` (public = unlimited free Actions minutes).
2. Push this code:
   ```sh
   cd /Users/phillipchaffee/git/slayyyter-tickets
   git init
   git add .
   git commit -m "initial commit"
   git remote add origin git@github.com:YOUR_USERNAME/slayyyter-tickets.git
   git branch -M main
   git push -u origin main
   ```

## 4. Add repo secrets

Settings → Secrets and variables → Actions → New repository secret.

**Required (minimum, ntfy-only):**

| Name | Value |
|---|---|
| `TICKETMASTER_API_KEY` | from step 1 |
| `SEATGEEK_CLIENT_ID` | from step 1 |
| `SEATGEEK_CLIENT_SECRET` | from step 1 |
| `NTFY_TOPIC` | the random topic from step 2 |

**Optional (only if you set up Gmail SMTP backup):**

| Name | Value |
|---|---|
| `SMTP_USER` | your Gmail address |
| `SMTP_PASS` | the 16-char app password |
| `SMTP_TO` | `phillipdensmorechaffee@gmail.com` |

## 5. Grant workflow write access

Settings → Actions → General → Workflow permissions → **Read and write**.
This lets the workflow commit `data/*` back to the repo each poll.

## 6. Discover event IDs

Run the bootstrap locally (it'll search both APIs and write the IDs into `config.yaml`):

```sh
export TICKETMASTER_API_KEY=...
export SEATGEEK_CLIENT_ID=...
export SEATGEEK_CLIENT_SECRET=...

.venv/bin/python -m monitor.bootstrap
```

It'll print candidates and prompt you to pick one per source. Then commit:

```sh
git add config.yaml
git commit -m "config: set event IDs"
git push
```

## 7. Trigger the first run

GitHub → Actions → "poll" → "Run workflow" → check **Poll even if not due** → Run.

Verify:
- The workflow run is green.
- A new commit appears on `main` from `github-actions[bot]` updating `data/`.
- A `daily_heartbeat` push lands in your ntfy app within ~30s (assuming you triggered between 9–10am PT — otherwise no heartbeat is fired and you'll just see fresh data committed).

## 8. Mid-campaign tuning

You'll get automatic threshold-revision alerts on **Aug 1** and **Aug 20** at 9am PT.
To revise: edit `config.yaml` (e.g. `threshold_usd: 200.0`), commit, push.
The next scheduled poll picks up the new value.

## Kill switches

| Goal | How |
|---|---|
| Pause alerts but keep collecting data | `paused: true` in `config.yaml` |
| Stop polling entirely | Rename `.github/workflows/poll.yml` → `poll.yml.disabled`, push |
| Disable a single rule | Set `enabled: false` under that rule in `config.yaml` |
| Rotate a leaked API key | Regenerate on the provider, update repo secret, no code change needed |

## Troubleshooting

- **Workflow runs but no commit appears.** Check `data/` actually changed in the run logs. The workflow skips commits when nothing changed.
- **No notifications arriving.** Run the workflow with `--force` and check the run log for `delivery failed` messages. Verify your ntfy topic is correct (case-sensitive).
- **Workflow disabled after ~60 days.** Should never happen because we commit data each run. If it does, GitHub will email you; manually re-enable in Actions.
- **Threshold alert never fires.** That's exactly why the last-48h backstop exists — it'll fire on Sep 6/7/8 mornings + evenings regardless.
