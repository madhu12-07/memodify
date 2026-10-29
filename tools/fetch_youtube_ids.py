#!/usr/bin/env python3
"""Looks up YouTube video ids for songs in advance and saves them in data/youtube_ids.csv.

Why: the site plays songs inside its own page with YouTube's embedded player, which needs a video id per song.
Ids found here are used with ZERO API quota afterwards. (Without this tool the site also looks songs up one by one
while people listen, and caches them.)

Uses only the Python standard library. Needs a free YouTube Data API v3 key (see README).

  python tools/fetch_youtube_ids.py                                # uses the key from .env; next 90 songs (a free key allows ~100 searches a day)
  python tools/fetch_youtube_ids.py --key YOUR_KEY --per-mood 15   # spread over all moods (top songs of each mood first)
  python tools/fetch_youtube_ids.py --dry-run                      # just show what would be searched

You can also open data/youtube_ids.csv and add rows by hand (title, movie, and a YouTube link or 11-letter id).
Run it again tomorrow: songs already in the file are skipped, so it simply carries on.
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import youtube  # noqa: E402
from app import load_env_file  # noqa: E402

load_env_file(ROOT / ".env")      # so the key in .env is found automatically (no --key needed)

FIELDS = ["title", "movie", "video_id"]


def tamil_head(song_id):
    import sqlite3
    con = sqlite3.connect(ROOT / "data" / "lyrics.db")
    try:
        row = con.execute("SELECT substr(tamil, 1, 700) FROM lyrics WHERE id = ?", (song_id,)).fetchone()
    finally:
        con.close()
    return row[0] if row and row[0] else ""


def read_songs(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def pick_songs(songs, per_mood):
    """Best-confidence songs of every mood first, round-robin, so each mood gets songs that play."""
    by_mood = {}
    for s in songs:
        by_mood.setdefault(s["mood"], []).append(s)
    for lst in by_mood.values():
        lst.sort(key=lambda s: -float(s.get("confidence") or 0))
        del lst[per_mood:]
    order = []
    for i in range(per_mood):
        for lst in by_mood.values():
            if i < len(lst):
                order.append(lst[i])
    return order


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=os.environ.get("YOUTUBE_API_KEY", ""), help="YouTube Data API key (or set YOUTUBE_API_KEY)")
    ap.add_argument("--songs", default=str(ROOT / "data" / "songs.csv"))
    ap.add_argument("--out", default=str(ROOT / "data" / "youtube_ids.csv"))
    ap.add_argument("--limit", type=int, default=90, help="max searches this run (default 90; free quota is ~100/day)")
    ap.add_argument("--per-mood", type=int, default=40, help="consider this many top songs per mood (default 40)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out)
    known = youtube.KnownIds(out, ROOT / "data" / "curated_seed.csv")
    todo = [s for s in pick_songs(read_songs(args.songs), args.per_mood)
            if not known.get(s["title"], s["movie"])][: args.limit]
    print(f"{len(todo)} song(s) to look up.")
    if args.dry_run or not todo:
        for s in todo:
            print("  would search:", youtube.query_for(s))
        return 0
    if not args.key:
        print("No API key. Pass --key YOUR_KEY or set YOUTUBE_API_KEY (see README).")
        return 2

    new_file = not out.exists() or out.stat().st_size == 0
    found = missed = 0
    with open(out, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(FIELDS)
        for s in todo:
            head = tamil_head(s["id"])
            ids, reason = youtube.search_song(args.key, {**s, "tamil_head": head})
            if reason in ("quota", "key"):
                print({"quota": "Daily quota used up - run again tomorrow, it carries on where it stopped.",
                       "key": "The API key was rejected - check it in Google Cloud Console."}[reason])
                break
            if reason == "error":
                print("  network/API error, stopping. Try again later.")
                break
            if not ids:
                missed += 1
                print("  no result:", s["title"])
                continue
            for vid in ids[:4]:                       # several candidates: the page tries the next if one will not embed
                w.writerow([s["title"], s["movie"], vid])
            f.flush()
            found += 1
            print(f"  ok  {s['title']}  ->  {ids[0]}")
            time.sleep(0.2)
    print(f"Done. Found {found}, no result {missed}. Saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
