# @everylotSJ

A Mastodon bot that posts one San José address every 2 minutes with a Google Street View photo. 394,000 addresses. ~1.5 years of content.

**Follow the bot: [mastodon.social/@everylotsj](https://mastodon.social/@everylotsj)**

Inspired by [@everylotNYC](https://twitter.com/everylotnyc) and based on the [everylot](https://github.com/fitnr/everylot) project by [@fitnr](https://github.com/fitnr).

Each post looks like:

```
📍 1739 Mirassou Pl San Jose CA 95124
🏡 Property type: Single Family
🗺️ https://maps.google.com/?q=37.2468,-121.8731
#SanJose #everylotSJ
```

...with a Google Street View image attached. If Street View has no coverage, it falls back to Mapillary imagery. If neither is available, the post goes out text-only.

For commercial addresses (property type `BU`), the bot also looks up the business name via Google Places:

```
📍 123 Main St San Jose CA 95110
🏬 Property type: Commercial / Business
🏪 Some Business Name
🗺️ https://maps.google.com/?q=37.33,-121.88
#SanJose #everylotSJ
```

Property type codes:

| Code | Emoji | Label |
|------|-------|-------|
| SF | 🏡 | Single Family |
| MF | 🏘️ | Multi-Family |
| BU | 🏬 | Commercial / Business |
| MH | 🚐 | Mobile Home |
| CO | 🏢 | Condo |
| TR | 🚉 | Transit / Transportation |

The bot's Mastodon bio updates automatically as it moves through zip codes and neighborhoods. It also marks milestones (1k, 5k, 10k, 50k, 100k posts) in the bio temporarily.

---

## How it works

1. `setup_db.py` downloads ~395,000 active San José address points from the city's ArcGIS MapServer into a local SQLite database (`lots.db`). Each record has a street address, latitude/longitude, property type, zip code, and neighborhood.
2. `bot.py` picks the next unposted address in order, fetches a Street View (or Mapillary) image, formats the post, publishes it to Mastodon, and marks that address as done.
3. A cron job runs `bot.py` every 2 minutes automatically.
4. `maintenance.py` can be run periodically to check database integrity and reclaim disk space.

After each successful post, `metrics.json` is updated with progress stats.

---

## Step 1 — Create your Mastodon account

1. Sign up at [mastodon.social](https://mastodon.social) (or any instance).
2. Go to **Preferences → Development → New Application**.
3. Name it anything (e.g. "everylotSJ bot") and check these scopes: `write:statuses`, `write:media`, `write:accounts`.
4. Click **Submit**, open the app, and copy:
   - Client key → `MASTODON_CLIENT_KEY`
   - Client secret → `MASTODON_CLIENT_SECRET`
   - Access token → `MASTODON_ACCESS_TOKEN`
5. Set `MASTODON_INSTANCE_URL` to your instance URL (e.g. `https://mastodon.social`).

---

## Step 2 — Get a Google API key

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Create a project (or reuse one).
3. Under **APIs & Services → Library**, enable:
   - **Street View Static API**
   - **Places API (New)** (for business name lookup on commercial addresses)
4. Under **APIs & Services → Credentials**, create an **API key**.
5. Copy it into `GOOGLE_API_KEY`.

**Cost:** Street View Static is ~$7 per 1,000 images. Google gives every account $200/month free credit. At one post every 2 minutes (~720 images/day, ~21,600/month) you'll stay within the free tier.

---

## Step 3 — Get a Mapillary token (optional)

Mapillary provides free street-level imagery as a fallback when Google Street View has no coverage.

1. Sign up at [mapillary.com](https://www.mapillary.com).
2. Go to [mapillary.com/developer](https://www.mapillary.com/developer) and register an application.
3. Copy the client token into `MAPILLARY_ACCESS_TOKEN`.

---

## Step 4 — Set up health checks (optional)

Get alerted if the bot stops posting.

1. Sign up at [healthchecks.io](https://healthchecks.io).
2. Create a check with a 10-minute period.
3. Copy the ping URL into `HEALTHCHECK_URL`.

---

## Step 5 — Clone and install

```bash
git clone https://github.com/RamonGarciaGomez/everylotsj.git
cd everylotsj
pip install -r requirements.txt
```

---

## Step 6 — Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in your keys. Never commit this file — it's in `.gitignore`.

---

## Step 7 — Build the database

Downloads all ~395k San José addresses into `lots.db`:

```bash
# Test with a small batch first
python setup_db.py --limit 2000

# Full load (~15 minutes)
python setup_db.py

# Start over from scratch
python setup_db.py --reset
```

---

## Step 8 — Test with a dry run

```bash
# Preview the next post without publishing
python bot.py --dry-run

# Preview a specific address by ID
python bot.py --dry-run --id 12345
```

---

## Step 9 — Post for real

```bash
python bot.py
```

---

## Step 10 — Set up the cron job

```bash
mkdir -p logs
crontab -e
```

Paste this line (update the path):

```
*/2 * * * * cd /path/to/everylotsj && /path/to/venv/bin/python3 bot.py >> logs/bot.log 2>&1
```

Verify with `crontab -l`.

---

## Step 11 — Maintenance (optional)

Run periodically to check database integrity and reclaim disk space:

```bash
python maintenance.py
```

To backfill Street View images for addresses that were posted text-only:

```bash
python bot.py --backfill
```

---

## Files

| File | Purpose |
|------|---------|
| `setup_db.py` | Downloads San José address points and builds `lots.db` |
| `bot.py` | Picks the next address, fetches imagery, posts to Mastodon |
| `maintenance.py` | Database integrity check and VACUUM |
| `requirements.txt` | Python dependencies |
| `.env.example` | Credential template — copy to `.env` and fill in |
| `metrics.json` | Auto-generated after each post with progress stats |

---

## Troubleshooting

- **"No unposted lots remaining"** — reset the queue: `sqlite3 lots.db 'UPDATE lots SET posted = 0'`
- **"Missing Mastodon credentials"** — make sure `.env` has all four `MASTODON_*` values filled in.
- **No Street View image** — the bot checks availability first, then tries Mapillary, then posts text-only.
- **Bio not updating** — make sure your Mastodon app has the `write:accounts` scope enabled.
- **Business names not showing** — make sure **Places API (New)** is enabled in Google Cloud Console.

---

## License

MIT. Address data is public record from the City of San José.
