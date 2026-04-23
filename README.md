# @everylotSJ

A Twitter/X bot that posts one San Jose property per hour with a Google
Street View photo and fun assessor facts (zoning, lot size, assessed value).

Inspired by [@everylotNYC](https://twitter.com/everylotnyc) and based on the [everylot](https://github.com/fitnr/everylot) project by [@fitnr](https://github.com/fitnr).

Each tweet looks like:

```
📍 1234 Elm St, San Jose CA
🏠 Zoning: R1 (Single-Family Residential)
📐 Lot size: 6,200 sq ft
💰 Assessed value: $820,000
   └ Land: $410,000
   └ Building: $410,000
#SanJose #everylotSJ
```

...with a Street View image attached.

---

## Step 1 — Get your API keys

### Twitter / X (four keys)

1. Go to <https://developer.twitter.com> and sign in.
2. Apply for a developer account if you don't have one (Free tier is enough
   to post ~500 tweets/month, which is plenty for hourly posting).
3. Create a new **Project** and inside it create an **App**.
4. In the App settings, enable **"Read and Write"** permissions
   (required to post tweets). If you change this after generating tokens,
   you'll need to regenerate them.
5. Generate and copy these four values:
   - API Key (`TWITTER_API_KEY`)
   - API Secret (`TWITTER_API_SECRET`)
   - Access Token (`TWITTER_ACCESS_TOKEN`)
   - Access Token Secret (`TWITTER_ACCESS_TOKEN_SECRET`)

### Google Cloud (one key)

1. Go to <https://console.cloud.google.com>.
2. Create a new project (or reuse one).
3. Under **APIs & Services → Library**, enable:
   - **Street View Static API**
   - **Geocoding API** (optional, for address → lat/lon fallbacks)
4. Under **APIs & Services → Credentials**, create an **API key**.
5. Copy the key into `GOOGLE_API_KEY`.

Cost note: Street View Static is ~$7 per 1,000 images, and Google gives
every account a $200/month free credit. At one tweet per hour (~720
images/month), you stay well inside the free tier.

---

## Step 2 — Clone and install

```bash
git clone <this repo>
cd everylotSJ
pip install -r requirements.txt
```

(If you prefer, create a virtualenv first:
`python3 -m venv .venv && source .venv/bin/activate`.)

---

## Step 3 — Configure credentials

```bash
cp .env.example .env
```

Open `.env` in your editor and paste in the keys from Step 1.
Never commit `.env` — it's in `.gitignore`.

---

## Step 4 — Build the database

The database (`lots.db`) combines two data sources:

1. San Jose open-data parcels CSV (addresses, zoning, geometry)
2. Santa Clara County Assessor web lookup (assessed values)

Start with a small test run:

```bash
python setup_db.py --limit 1000
```

That downloads the CSV (~50-100 MB) and enriches the first 1,000 parcels.
The enrichment step is slow (2-second rate limit per lookup), so 1,000
lots takes ~35 minutes.

When you're satisfied, do the full run:

```bash
python setup_db.py
```

The full dataset is ~200,000 parcels; enrichment will take several hours
(or days if you let it run in the background). You can also skip
enrichment up front and let the bot do it lazily per tweet:

```bash
python setup_db.py --skip-enrich
```

---

## Step 5 — Dry-run test

Preview the next tweet without posting:

```bash
python bot.py --dry-run
```

This prints the formatted tweet and confirms the Street View image would
fetch. No data is written, no tweet is sent.

You can also target a specific parcel by APN:

```bash
python bot.py --dry-run --id 123-45-678
```

---

## Step 6 — Post your first tweet for real

```bash
python bot.py
```

The bot will:
- pick the next unposted lot from `lots.db`
- fetch (and cache) assessor data if missing
- fetch a Street View image
- post the tweet
- mark the lot as posted and record the tweet ID

Check your account — you should see the tweet.

---

## Step 7 — Automate with cron

```bash
mkdir -p logs
crontab -e
```

Paste one of the lines from `crontab_example.txt` (adjust the path to
where you cloned this repo). Confirm with `crontab -l`.

---

## Files

| File                   | Purpose                                              |
| ---------------------- | ---------------------------------------------------- |
| `setup_db.py`          | Download parcels CSV → build & enrich `lots.db`      |
| `enrichment.py`        | Santa Clara County assessor value lookup             |
| `bot.py`               | Post one lot per run                                 |
| `requirements.txt`     | Python dependencies                                  |
| `.env.example`         | Template for credentials                             |
| `crontab_example.txt`  | How to schedule hourly runs                          |

## Troubleshooting

- **"No unposted lots remaining"** — you've tweeted every lot. Congrats!
  Reset with `sqlite3 lots.db 'UPDATE lots SET posted = 0'`.
- **"Missing Twitter credentials"** — check that `.env` exists and has
  all four `TWITTER_*` values filled in.
- **Street View returns a gray placeholder** — the bot detects this via
  the metadata endpoint and posts the tweet without an image instead of
  crashing.
- **Assessor enrichment returns all `None`** — the county may have
  updated their site structure. Update `enrichment.py`'s parser to match.

## License

MIT. Assessor data and parcel data are public records from the County of
Santa Clara and the City of San Jose.
