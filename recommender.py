"""Loads the processed Tamil songs library (data/songs.csv + data/lyrics.db)."""
import csv
import random
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus

from moods import MOODS

REQUIRED = {"id", "title", "mood"}


class SongLibrary:
    def __init__(self, path):
        self.path = Path(path)
        self.lyrics_path = self.path.with_name("lyrics.db")
        self.songs = []
        self.by_id = {}
        self.by_mood = {m: [] for m in MOODS}
        self._with_lyrics = None
        self._load()

    def _load(self):
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = REQUIRED - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"songs file is missing columns: {sorted(missing)}")
            for row in reader:
                title = (row.get("title") or "").strip()
                mood = (row.get("mood") or "").strip().lower()
                try:
                    sid = int(row["id"])
                except (TypeError, ValueError):
                    continue
                if not title or mood not in MOODS or sid in self.by_id:
                    continue

                def num(key, default):
                    try:
                        return float(row.get(key) or default)
                    except ValueError:
                        return default

                song = {
                    "id": sid,
                    "title": title,
                    "movie": (row.get("movie") or "").strip(),
                    "year": int(row["year"]) if (row.get("year") or "").isdigit() else None,
                    "music_director": (row.get("music_director") or "").strip(),
                    "mood": mood,
                    "confidence": num("confidence", 0.5),
                    "valence": num("valence", 0.5),
                    "energy": num("energy", 0.5),
                    "source_link": (row.get("source_link") or "").strip(),
                }
                # optional extra: a YouTube *search* link (never the main way to listen)
                song["search_url"] = ("https://www.youtube.com/results?search_query="
                                      + quote_plus(f"{title} {song['movie']} tamil song".strip()))
                self.songs.append(song)
                self.by_id[sid] = song
                self.by_mood[mood].append(song)
        # best-matching songs first: the app only recommends from the more confident part of each mood
        for lst in self.by_mood.values():
            lst.sort(key=lambda s: -s["confidence"])

    def get(self, song_id):
        return self.by_id.get(song_id)

    def lyrics(self, song_id):
        """{'tamil': str, 'english': str} or None. Read straight from SQLite on demand."""
        if not self.lyrics_path.exists():
            return None
        con = sqlite3.connect(f"file:{self.lyrics_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT tamil, english FROM lyrics WHERE id = ?", (song_id,)).fetchone()
        finally:
            con.close()
        return {"tamil": row[0], "english": row[1]} if row else None

    def has_lyrics(self, song_id):
        """True when real lyrics are stored for this song (a few newest songs have none)."""
        if self._with_lyrics is None:
            self._with_lyrics = set()
            if self.lyrics_path.exists():
                con = sqlite3.connect(f"file:{self.lyrics_path}?mode=ro", uri=True)
                try:
                    self._with_lyrics = {r[0] for r in con.execute(
                        "SELECT id FROM lyrics WHERE length(tamil) > 60 OR length(english) > 60")}
                finally:
                    con.close()
        return song_id in self._with_lyrics

    def _era(self, mood, years, minimum=24):
        """Songs of `mood` released in years=(first, last). Widens the range (3 years each side, up to 15)
        when there are too few, so no mood/age combination is ever empty. years=None -> every year."""
        lst = self.by_mood.get(mood, [])
        if not years:
            return lst
        lo, hi = years
        for _ in range(6):
            sel = [s for s in lst if s["year"] and lo <= s["year"] <= hi]
            if len(sel) >= minimum:
                return sel
            lo, hi = lo - 3, hi + 3
        return sel or lst

    def pool(self, mood, keep=0.6, years=None):
        """The top `keep` share (by confidence) of a mood's songs, limited to an era when `years` is given."""
        lst = self._era(mood, years)
        return lst[: max(8, int(len(lst) * keep))]

    def recommend(self, mood, limit=8, exclude_ids=(), years=None):
        pool = self.pool(mood, years=years)
        ex = set(exclude_ids)
        fresh = [s for s in pool if s["id"] not in ex]
        random.shuffle(fresh)
        picked = fresh[:limit]
        if len(picked) < limit:                      # everything was shown already: top up
            rest = [s for s in pool if s not in picked]
            random.shuffle(rest)
            picked += rest[: limit - len(picked)]
        return picked
