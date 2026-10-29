#!/usr/bin/env python3
"""Builds data/video_index.csv: a local list of songs from official YouTube channels.

WHY: searching YouTube costs 100 quota units per song and a free key only has 10,000 units a day (~100 searches).
Listing a channel's uploads costs about 1 unit per 50 videos, so ONE run of this tool covers thousands of songs.
The app then finds songs in this file first (zero quota) and only searches YouTube for songs that are not in it.

Only videos that are public, embeddable and 75 s - 12 min long are saved (so scenes / trailers / full movies are left out).

Usage:
  python tools/build_video_index.py                       # key from .env, channels from data/channels.txt
  python tools/build_video_index.py --max-pages 60        # up to 60 pages (3,000 videos) per channel per run
Run it again any time: it carries on where it stopped and never repeats videos. ~2 units per 50 videos.
"""
import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import youtube  # noqa: E402

API = "https://www.googleapis.com/youtube/v3/"


def call(endpoint, key, **params):
    params["key"] = key
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        if "quotaExceeded" in body:
            raise SystemExit("Daily quota used up. Run this tool again tomorrow - it carries on where it stopped.")
        raise SystemExit(f"YouTube API error {e.code}: {body[:300]}")


def load_env():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def uploads_playlist(key, ref):
    p = {"part": "contentDetails,snippet"}
    if ref.startswith("@"):
        p["forHandle"] = ref
    else:
        p["id"] = ref
    items = call("channels", key, **p).get("items", [])
    if not items:
        return None, None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"], items[0]["snippet"]["title"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key")
    ap.add_argument("--channels", default=str(ROOT / "data" / "channels.txt"))
    ap.add_argument("--out", default=str(ROOT / "data" / "video_index.csv"))
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)
    load_env()
    key = args.key or os.environ.get("YOUTUBE_API_KEY", "")
    region = args.region or os.environ.get("YOUTUBE_REGION", "IN")
    if not key:
        print("No API key. Use --key or put YOUTUBE_API_KEY in .env")
        return 2
    out = Path(args.out)
    state_file = out.with_suffix(".state.json")
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    have = set()
    if out.exists():
        with open(out, newline="", encoding="utf-8") as f:
            have = {r["video_id"] for r in csv.DictReader(f)}
    new_file = not out.exists()
    refs = [l.strip() for l in open(args.channels, encoding="utf-8") if l.strip() and not l.startswith("#")]
    added = 0
    with open(out, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["video_id", "title", "channel", "seconds"])
        for ref in refs:
            st = state.get(ref, {})
            if st.get("done"):
                print(f"{ref}: already complete")
                continue
            playlist = st.get("playlist")
            name = st.get("name", ref)
            if not playlist:
                playlist, name = uploads_playlist(key, ref)
                if not playlist:
                    print(f"{ref}: NOT FOUND - check the handle spelling or use the UC... channel id")
                    continue
            token, pages, n_add = st.get("token"), 0, 0
            while pages < args.max_pages:
                p = {"part": "snippet", "playlistId": playlist, "maxResults": 50}
                if token:
                    p["pageToken"] = token
                data = call("playlistItems", key, **p)
                vids = [(it["snippet"]["resourceId"]["videoId"], it["snippet"]["title"])
                        for it in data.get("items", []) if it.get("snippet", {}).get("resourceId")]
                vids = [(v, t) for v, t in vids if youtube.clean_video_id(v) and v not in have]
                if vids:
                    det = call("videos", key, part="status,contentDetails", id=",".join(v for v, _ in vids)).get("items", [])
                    info = {d["id"]: d for d in det}
                    for v, t in vids:
                        d = info.get(v)
                        if not d:
                            continue
                        s, cd = d.get("status", {}), d.get("contentDetails", {})
                        rr = cd.get("regionRestriction") or {}
                        secs = youtube._seconds(cd.get("duration"))
                        if s.get("embeddable") is False or s.get("privacyStatus") != "public":
                            continue
                        if region in (rr.get("blocked") or []) or (rr.get("allowed") is not None and region not in rr["allowed"]):
                            continue
                        if secs is None or not (75 <= secs <= 720):
                            continue
                        w.writerow([v, t, name, secs])
                        have.add(v)
                        n_add += 1
                pages += 1
                token = data.get("nextPageToken")
                state[ref] = {"playlist": playlist, "name": name, "token": token, "done": not token}
                state_file.write_text(json.dumps(state))
                f.flush()
                if not token:
                    break
            added += n_add
            print(f"{name}: +{n_add} songs ({'complete' if state[ref]['done'] else 'more next run'})")
    print(f"Done. {added} songs added, {len(have)} in {out.name}. Restart is NOT needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
