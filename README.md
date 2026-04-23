# @everylotSJ

A Twitter/X bot that posts one San Jose address per hour with a Google Street View photo.

Inspired by [@everylotNYC](https://twitter.com/everylotnyc) and based on the [everylot](https://github.com/fitnr/everylot) project by [@fitnr](https://github.com/fitnr).

Each tweet looks like:

```
📍 1 Almaden Blvd 1150 San Jose CA 95113
🏠 Commercial / Business
#SanJose #everylotSJ
```

...with a Google Street View image attached.

Property type labels:

| Code | Label |
|------|-------|
| SF | Single Family |
| MF | Multi-Family |
| BU | Commercial / Business |
| MH | Mobile Home |
| CO | Condo |
| TR | Transit / Transportation |

---

## How it works

1. `setup_db.py` downloads ~395,000 active San Jose address points from the city's ArcGIS MapServer into a local SQLite database (`lots.db`). Each record has a street address, latitude/longitude, and property type.
2. `bot.py` picks the next unposted address, fetches a Street View image from Google, formats the tweet, posts it, and marks that address as done so it's never posted again.
3. A cron job runs `bot.py` once an hour automatically.

---

## Step 1 — Get your API keys

### Twitter / X (four keys)

1. Go to <https://developer.twitter.com> and sign in.
2. Apply for a developer account if you don't have one (the Free tier is enough — it allows ~500 tweets/month, more than enough for hourly posting).
3. Create a new **Project** and inside it create an **App**.
4. In the App settings, set permissions to **"Read and Write"**. If you change this after generating tokens, regenerate them.
5. Copy these four values:
   - API Key → `TWITTER_API_KEY`
   - API Secret → `TWITTER_API_SECRET`
   - Access Token → `TWITTER_ACCESS_TOKEN`
   - Access Token Secret → `TWITTER_ACCESS_TOKEN_SECRET`

### Google Cloud (one key)

1. Go to <https://console.cloud.google.com>.
2. Create a project (or reuse an existing one).
3. Under **APIs & Services → Library**, enable the **Street View Static API**.
4. Under **APIs & Services → Credentials**, create an **API key**.
5. Copy it into `GOOGLE_API_KEY`.

**Cost note:** Street View Static is ~$7 per 1,000 images. Google gives every account $200/month in free credit. At one tweet per hour (~720 images/month) you stay comfortably within the free tier.

---

## Step 2 — Clone and install

```bash
git clone https://github.com/RamonGarciaGomez/everylotsj.git
cd everylotsj
pip install -r requirements.txt
```

Tip: use a virtualenv to keep dependencies isolated:
```bash
python3 -m venv .venv && source .venv/bin/activate
```

---

## Step 3 — Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in your API keys. Never commit this file — it's already in `.gitignore`.

---

## Step 4 — Build the database

This downloads all San Jose address points from the city's open GIS API and loads them into `lots.db`.

Test with a small batch first:

```bash
python setup_db.py --limit 2000
```

Then run the full load (~395k addresses, takes about 15 minutes):

```bash
python setup_db.py
```

To start over from scratch:

```bash
python setup_db.py --reset
```

---

## Step 5 — Test with a dry run

Preview the next tweet without actually posting it:

```bash
python bot.py --dry-run
```

Test a specific address by its database ID:

```bash
python bot.py --dry-run --id 12345
```

---

## Step 6 — Post your first tweet

```bash
python bot.py
```

The bot will:
- Pick the next unposted address from `lots.db`
- Check if Street View imagery exists for that location
- Fetch the Street View image (if available)
- Post the tweet (with image if available, text-only if not)
- Mark the address as posted and save the tweet ID

Check your Twitter account — the tweet should appear within seconds.

---

## Step 7 — Automate with cron

```bash
mkdir -p logs
crontab -e
```

Paste the line from `crontab_example.txt`, updating the path to where you cloned the repo. Verify with `crontab -l`.

---

## Files

| File | Purpose |
|------|---------|
| `setup_db.py` | Downloads San Jose address points and builds `lots.db` |
| `bot.py` | Picks the next address, fetches Street View, posts the tweet |
| `requirements.txt` | Python dependencies |
| `.env.example` | Credential template — copy to `.env` and fill in |
| `crontab_example.txt` | How to schedule hourly runs |

---

## Troubleshooting

- **"No unposted lots remaining"** — the bot has tweeted every address. Reset the queue with `sqlite3 lots.db 'UPDATE lots SET posted = 0'`.
- **"Missing Twitter credentials"** — make sure `.env` exists and all four `TWITTER_*` values are filled in.
- **No Street View image** — the bot checks the Street View metadata endpoint before fetching. If no imagery exists for a location, it posts text-only instead of crashing.

---

## License

MIT. Address data is public record from the City of San Jose.
