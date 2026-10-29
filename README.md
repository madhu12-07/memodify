# Memodify - Tamil Mood Music Recommender

A Flask web app that recommends **only Tamil songs** (from your Tamil lyrics dataset, 5,348 songs, 1954-2020)
based on your mood. The app is in English; **only the mood quiz is Tamil + English**.

Flow: **Home -> Detect Mood -> choose your age group -> choose Face, Quiz or Emoji -> songs from the years you grew up with**. The three ways appear on the Detect page only:

1. **Face** - the camera reads your expression (runs in your browser, video never leaves your device)
2. **Quiz** - 5 short questions, each shown in Tamil and English
3. **Emoji** - tap one emoji

...then take the **Mood Journey**.

## The unique part: Mood Journey

You pick where you are now (for example **Sad**) and how long the journey should be (20 / 30 / 45 / 60 minutes).
The playlist then walks towards a happy mood **on its own**, with nothing to analyse or tap:

```
Sad -> Calm -> Romantic -> Happy
```

* Every mood stage gets an equal slice of the time; when the slice is over, the next mood starts automatically.
* A live **mood curve** (graph) shows the planned route (dashed), the songs already played (solid) and where you are now.
* Pause, skip a song, or end the journey any time. A table version of the graph is available for screen readers.
* Without a YouTube key the app runs each song as a timed slot with its lyrics. A **Demo speed** option (10x / 30x)
  lets you see the whole journey in about a minute.

## Pages

| Page | URL | What it does |
|------|-----|--------------|
| Splash | `/` | Logo shows off ~3 s, then opens Login (or Home if already logged in) |
| Login / Sign up | `/login` | Email + password and **Continue with Google** |
| Home | `/home` | Stats, **Detect Mood** button, Mood Journey, recent moods |
| Detect Mood | `/detect` | Choose Face, Quiz or Emoji |
| Journey | `/journey` | The automatic Mood Journey with the live graph |
| Face / Quiz / Emoji | `/face` `/quiz` `/emoji` | The three ways to detect your mood |
| Results | `/results?mood=sad` | 8 songs for the mood, lyrics pop-up, favorites, shuffle |
| Favorites / History | `/favorites` `/history` | Hearted songs and your past moods |

## Run it in VS Code

1. Install **Python 3.10+** and VS Code.
2. **File > Open Folder...** and choose the project folder.
3. Open the terminal and run these **one line at a time**:

```bash
pip install -r requirements.txt
python app.py
```

4. Open **http://localhost:5000** in Chrome or Edge (the camera only works on `localhost` or `https`).

Optional virtual environment (if you want one): `python -m venv venv`, then call its Python directly
(`venv\Scripts\python.exe -m pip install -r requirements.txt` and `venv\Scripts\python.exe app.py` on Windows),
so you do not need the `activate` script. Keep the project **outside OneDrive** if venv creation is very slow.

## Tests

```bash
pytest -q
```

## About the dataset and the mood labels

`data/songs.csv` and `data/lyrics.db` were built from `Tamil_lyrics_v1.csv` (the DravidianLangTech 2021 lyrics dataset
you supplied). Only songs from this dataset are used.

**Important - be honest about accuracy:** the dataset has lyrics but **no mood column**, so the mood of each song is
*estimated from its lyrics* (Tamil keyword lexicon + a small text classifier). On 36 songs labelled by hand the guess was
exactly right **39%** of the time and on the right positive/negative side **69%** of the time
(see `data/mood_model_report.txt`). Treat it as "good enough to explore", not as ground truth. The results page says so.
You can improve it any time by adding hand-labelled songs to `data/curated_seed.csv` and rebuilding.

**Songs play inside the website:** the dataset has lyrics only (no audio, no YouTube links), so songs are played with
YouTube's **embedded player** inside your own pages (Results, Favorites and the Mood Journey). Nobody is sent to
youtube.com. This needs one thing from you: a free YouTube API key - see **Play songs inside the website** below.

### Rebuild the dataset (only if you change the data)

```bash
pip install -r tools/requirements-build.txt
python tools/build_dataset.py --input path/to/Tamil_lyrics_v1.csv
```

This rewrites `data/songs.csv` and `data/lyrics.db`. Restart the app afterwards.

## Optional: Continue with Google

Email sign-up works with no setup. For the Google button:

1. <https://console.cloud.google.com/> - create a project.
2. **APIs & Services > OAuth consent screen** - External - fill app name and your email.
3. **Credentials > Create credentials > OAuth client ID > Web application**.
4. Add **both** `http://localhost:5000` and `http://127.0.0.1:5000` under **Authorized JavaScript origins** (the address in the browser must match exactly).
5. Copy `.env.example` to `.env` and set `GOOGLE_CLIENT_ID=...`, then restart the app.

## Play songs inside the website

Songs need a YouTube video id. Pick **A** (recommended) and/or **B**:

**A - API key (finds songs by itself, 3 minutes, free)**

1. <https://console.cloud.google.com/> - create/select a project.
2. **APIs & Services > Library** - enable **YouTube Data API v3**.
3. **Credentials > Create credentials > API key**.
4. Copy `.env.example` to `.env`, set `YOUTUBE_API_KEY=your_key`, restart `python app.py`.

Official songs are preferred (official audio / video first, then lyric videos; covers, remixes and live clips are pushed down),
and videos that are private, not embeddable or blocked in your country (`YOUTUBE_REGION`, default `IN`) are dropped.
If a saved video stops working it is forgotten and searched again once.

Now press **▶** on any song: the app looks the song up once, caches it, and plays it in the page. If a video refuses
to embed, the next search result is tried automatically; when a song ends the next one starts by itself.

The free quota is about **100 song lookups per day** (YouTube's rule). Cached songs cost nothing, and you can fill the
cache ahead of time (it carries on where it stopped every day):

```bash
python tools/fetch_youtube_ids.py --key YOUR_KEY --per-mood 15
```

**B - your own list (no key, no quota)**

Open `data/youtube_ids.csv` and add rows: `title,movie,video_id` (the video id or a normal YouTube link both work;
use the same title and movie as in the app). Saved changes work immediately, no restart. Several rows for one song = backups.

Songs with no id and no key cannot play inside the page; the player says so (and offers a YouTube link only in that case).
YouTube's own player, logo and ads stay as they are - that is YouTube's rule for embedded videos. There is no download button.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Camera does not start | Use `http://localhost:5000`, allow the camera, close Zoom/Teams |
| Face models fail to load | Make sure `static/vendor/face-api/model` exists and the server is running |
| Press play, nothing plays and a yellow-ish message appears | Read the message: usually the YouTube key is missing, or the daily 100-lookup limit is used (try tomorrow, or fill `data/youtube_ids.csv`) |
| Google button says not set up | Add `GOOGLE_CLIENT_ID` to `.env`, restart |
| Port already used | `set PORT=5001` (Windows) or `PORT=5001 python app.py` (Mac/Linux) |
| `pip` or `python` not recognised | Reinstall Python with "Add python.exe to PATH" ticked, or use `py -m pip` and `py app.py` |

Face-detection library: [@vladmandic/face-api](https://github.com/vladmandic/face-api) (MIT, bundled in `static/vendor/face-api`).


## Age groups

Pick an age group on the Detect page first. The mood decides the *feeling* of the songs, the age group decides the *era*
(the Mood Journey uses it too):

| Age group | Songs from |
|---|---|
| Under 18 | 2015-2020 |
| 18 - 25 | 2012-2020 |
| 26 - 35 | 2005-2016 |
| 36 - 50 | 1994-2008 |
| 51 - 65 | 1978-1995 |
| 65 + | 1954-1985 |

If a mood has too few songs in an era, the range is widened a few years so you always get a full list. Change the table in `moods.py` (`AGE_GROUPS`).

## About the video

YouTube only allows its player to be embedded when it stays visible, so the song's video shows in a small glass frame while it plays.
Hiding or covering it would break YouTube's rules and could get your API key blocked. Official *audio* uploads are ranked first, so for most songs you just see the cover art.


## Data fixes (title / lyrics / video matching)

* `python tools/fix_data.py` repairs songs whose lyrics were swapped with another song of the same movie and songs saved under
  a wrong title. The list of changes is in `data/data_fix_report.txt`; the untouched originals are in `data/_backup/`.
* About 163 of the newest songs (2020-2026) have **no lyrics** in the dataset. They still play; the lyrics button is dimmed.
* A video is used only if its title really contains the song name (and the movie name or a near-exact match). If nothing matches,
  the page says so instead of playing a wrong song. Old cached video ids are forgotten automatically.

## No more "daily YouTube limit" (video index)

A YouTube **search costs 100 units** and a free key has **10,000 units a day**, so only ~100 songs can be searched per day.
Listing a channel's uploads costs about **1 unit per 50 videos**, so build a local song list once and the limit stops mattering:

```bash
python tools/build_video_index.py            # reads data/channels.txt (official Tamil label channels), key from .env
python tools/build_video_index.py            # run again later: it carries on where it stopped
```

* It saves only public, embeddable, 75 s - 12 min videos in `data/video_index.csv` (no scenes, trailers, full movies).
* The app looks in this file first (zero quota), then in your cache, and only then searches YouTube.
* If the daily limit IS used up, the app pauses searching for an hour, lists songs that can still play first, and the
  player jumps to the next ready song instead of stopping.
* Edit `data/channels.txt` to add or remove channels (`@handle` or `UC...` id). Quota resets at midnight Pacific time
  (about 1:30 PM India time). You can also ask Google for a higher quota (free form in the Cloud console).
