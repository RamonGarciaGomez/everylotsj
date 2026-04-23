# @everylotSJ

A Mastodon bot that posts one San Jose address per hour with a Google Street View photo.

Inspired by [@everylotNYC](https://twitter.com/everylotnyc) and based on the [everylot](https://github.com/fitnr/everylot) project by [@fitnr](https://github.com/fitnr).

Each post looks like:

```
📍 1739 Mirassou Pl San Jose CA 95124
🏡 Property type: Single Family
#SanJose #everylotSJ
```

...with a Google Street View image attached.

Property type codes:

| Code | Emoji | Label |
|------|-------|-------|
| SF | 🏡 | Single Family |
| MF | 🏘️ | Multi-Family |
| BU | 🏬 | Commercial / Business |
| MH | 🚐 | Mobile Home |
| CO | 🏢 | Condo |
| TR | 🚉 | Transit / Transportation |

---

## How it works

1. `setup_db.py` downloads ~395,000 active San Jose address points from the city's ArcGIS MapServer into a local SQLite database (`lots.db`). Each record has a street address, latitude/longitude, and property type.
2. `bot.py` picks the next unposted address, fetches a Street View image from Google, formats the post, publishes it to Mastodon, and marks that address as done so it's never posted again.
3. A cron job runs `bot.py` once an hour automatically.

At one post per hour it will take **45 years** to get through every address. Plenty of content.

---

## Step 1 — Create your Mastodon account

1. Sign up at [mastodon.social](https://mastodon.social) (or any instance).
2. Go to **Preferences → Development → New Application**.
3. Name it anything (e.g. "everylotSJ bot") and make sure `write:statuses` and `write:media` are checked under scopes.
4. Click **Submit**, open the app, and copy:
   - Client key → `MASTODON_CLIENT_KEY`
   - Client secret → `MASTODON_CLIENT_SECRET`
   - Access token → `MASTODON_ACCESS_TOKEN`
5. Set `MASTODON_INSTANCE_URL` to your instance URL (e.g. `https://mastodon.social`).

---

## Step 2 — Get a Google API key

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Create a project (or reuse one).
3. Under **APIs & Services → Library**, enable the **Street View Static API**.
4. Under **APIs & Services → Credentials**, create an **API key**.
5. Copy it into `GOOGLE_API_KEY`.

**Cost:** Street View Static is ~$7 per 1,000 images. Google gives every account $200/month free credit. At one post per hour (~720 images/month) you'll pay nothing.

---

## Step 3 — Clone and install

```bash
git clone https://github.com/RamonGarciaGomez/everylotsj.git
cd everylotsj
pip install -r requirements.txt
```

---

## Step 4 — Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in your keys. Never commit this file — it's in `.gitignore`.

---

## Step 5 — Build the database

Downloads all ~395k San Jose addresses into `lots.db`:

```bash
# Test with a small batch first
python setup_db.py --limit 2000

# Full load (~15 minutes)
python setup_db.py

# Start over from scratch
python setup_db.py --reset
```

---

## Step 6 — Test with a dry run

```bash
# Preview the next post without publishing
python bot.py --dry-run

# Preview a specific address by ID
python bot.py --dry-run --id 12345
```

---

## Step 7 — Post for real

```bash
python bot.py
```

---

## Step 8 — Set up the cron job

```bash
mkdir -p logs
crontab -e
```

Paste this line (update the path):

```
30 * * * * cd /path/to/everylotsj && python3 bot.py >> logs/bot.log 2>&1
```

Verify with `crontab -l`.

---

## Files

| File | Purpose |
|------|---------|
| `setup_db.py` | Downloads San Jose address points and builds `lots.db` |
| `bot.py` | Picks the next address, fetches Street View, posts to Mastodon |
| `requirements.txt` | Python dependencies |
| `.env.example` | Credential template — copy to `.env` and fill in |
| `crontab_example.txt` | How to schedule hourly runs |

---

## Troubleshooting

- **"No unposted lots remaining"** — reset the queue: `sqlite3 lots.db 'UPDATE lots SET posted = 0'`
- **"Missing Mastodon credentials"** — make sure `.env` has all four `MASTODON_*` values filled in.
- **No Street View image** — the bot checks availability before fetching and posts text-only if no imagery exists.

---

## License

MIT. Address data is public record from the City of San Jose.
