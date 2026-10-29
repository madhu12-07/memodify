"""Finds a playable YouTube video for a song, so the page can play it in its own embedded player.

Where video ids come from (checked in this order):

  1. data/youtube_ids.csv   - ids you add by hand or with tools/fetch_youtube_ids.py (no API quota used)
  2. data/curated_seed.csv  - the optional `youtube_id` column
  3. the cache table        - ids found earlier through the API
  4. YouTube Data API v3    - only when YOUTUBE_API_KEY is set; every answer is cached

The dataset itself has no audio and no video ids, and this module never invents one.
"""
import csv
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_ID_RE = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})")


def song_key(title, movie):
    return f"{title}|{movie}".lower()


def clean_video_id(value):
    """Accepts a bare 11-character id or any normal YouTube link; returns the id or ''."""
    value = (value or "").strip()
    if VIDEO_ID_RE.match(value):
        return value
    m = _URL_ID_RE.search(value)
    return m.group(1) if m else ""


def clean_id_list(values):
    seen, out = set(), []
    for v in values:
        v = clean_video_id(v)
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


class KnownIds:
    """Reads the id files and re-reads a file by itself when you edit it (no restart needed)."""

    def __init__(self, *paths):
        self.paths = [Path(p) for p in paths]
        self._stamp = None
        self._data = {}

    def _signature(self):
        sig = []
        for p in self.paths:
            try:
                st = p.stat()
                sig.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((str(p), None, None))
        return tuple(sig)

    def _load(self):
        data = {}
        for p in self.paths:
            if not p.exists():
                continue
            with open(p, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    title = (row.get("title") or "").strip()
                    movie = (row.get("movie") or "").strip()
                    vid = clean_video_id(row.get("video_id") or row.get("youtube_id") or "")
                    if title and vid:
                        ids = data.setdefault(song_key(title, movie), [])
                        if vid not in ids:
                            ids.append(vid)
        self._data = data

    def _refresh(self):
        sig = self._signature()
        if sig != self._stamp:
            self._load()
            self._stamp = sig

    def get(self, title, movie):
        self._refresh()
        return list(self._data.get(song_key(title, movie), []))

    def count(self):
        self._refresh()
        return len(self._data)


_BAD_WORDS = ("cover", "remix", "reaction", "karaoke", "whatsapp", "status", "8d", "slowed", "reverb", "mashup",
              "instrumental", "ringtone", "tiktok", "#shorts", "shorts", "full movie", "jukebox", "live", "dj", "bgm",
              "trailer", "teaser", "scene", "scenes", "comedy", "tutorial", "lesson", "how to play", "piano", "guitar",
              "sneak peek", "sneak", "peek", "climax", "glimpse", "promo", "making", "behind the scenes", "bts",
              "first look", "motion poster", "dialogue", "dialogues", "fight", "interview", "speech", "press meet",
              "audio launch", "launch", "review", "explained", "reels", "edit", "clip", "clips", "deleted",
              "spoof", "troll", "parody", "unplugged", "acoustic", "concert", "performance", "stage", "dance cover",
              "fan made", "fanmade", "lyrics in", "ringtone", "flute", "veena", "keyboard", "violin", "bgm")
_BAD_RE = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in sorted(set(_BAD_WORDS), key=len, reverse=True)) + r")(?![a-z0-9])")
_SONG_WORDS = re.compile(r"(?<![a-z0-9])(?:songs?|audio|lyric|lyrics|lyrical|video|official|music|full|single|track)(?![a-z0-9])")


def is_bad_title(text, allow=""):
    """True when the video title has a non-song word (scene, sneak peek, teaser...). Words that are part of the
    song's own name/movie (a song called 'Climax', a film called 'Live') do not count."""
    hits = set(_BAD_RE.findall((text or "").lower()))
    return bool(hits - set(_BAD_RE.findall((allow or "").lower())))


_LABELS = ("sony music", "think music", "lahari", "saregama", "divo", "aditya", "t-series", "muzik247", "eros",
           "zee music", "sun tv", "sun music", "ayngaran", "u1 records", "speed audio", "lyca", "trend music",
           "vevo", "records", "audios", "star music", "think originals", "sa re ga ma", "tips")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return [t for t in _WORD_RE.findall((text or "").lower()) if len(t) > 1]


def score(item, song=None):
    """Higher = more likely to be the OFFICIAL song (official audio/video first, lyric videos next)."""
    sn = (item or {}).get("snippet") or {}
    title, chan = (sn.get("title") or "").lower(), (sn.get("channelTitle") or "").lower()
    pts = 0.0
    if "official" in title or "official" in chan:
        pts += 4
    if any(l in chan for l in _LABELS):
        pts += 4
    if "audio" in title or "video song" in title or "full video" in title or "official video" in title:
        pts += 3
    if "lyric" in title:
        pts += 1                              # lyric videos are accepted, but below official audio / video
    if is_bad_title(title):
        pts -= 6
    if song:
        want = _tokens(song.get("title"))
        if want:
            have = set(_tokens(title))
            pts += 3.0 * sum(t in have for t in want) / len(want)
        mv = [t for t in _tokens(song.get("movie")) if len(t) > 2]
        if mv and any(t in title for t in mv):
            pts += 1
    return pts


import html as _html
import difflib

_TAMIL_RE = re.compile(r"[\u0b80-\u0bff]+")


def phon(text):
    """Rough Tamil-in-English-letters key, so 'Yaarovai' ~ 'Yaaro Vaai' and 'Kuzhaloodhum' ~ 'Kuzhaloothum'."""
    s = (text or "").lower().replace("zh", "l").replace("\u2019", "").replace("'", "")
    s = re.sub(r"([tdkgcbps])h", r"\1", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    s = re.sub(r"(.)\1+", r"\1", s)
    return s.replace("d", "t").replace("g", "k").replace("w", "v").replace("b", "p")


def title_fit(want, have):
    """0..1 - how well the song title (phonetic) appears inside the video title."""
    w, h = phon(want), phon(have)
    if not w or not h:
        return 0.0
    if w in h:
        return 1.0
    best, L = 0.0, len(w)
    for i in range(0, max(1, len(h) - L + 1)):
        for ln in (L, L + 1, max(1, L - 1)):
            r = difflib.SequenceMatcher(None, w, h[i:i + ln]).ratio()
            if r > best:
                best = r
    return best


def _tamil_words(text):
    return [w for w in _TAMIL_RE.findall(text or "") if len(w) >= 3]


def tamil_title_matches(video_title, lyrics_head):
    """For videos titled in Tamil letters: do most of the title's words appear in this song's own lyrics?"""
    words = _tamil_words(video_title)
    if not words or not lyrics_head:
        return False
    pool = _tamil_words(lyrics_head)
    hit = sum(any(w[:4] == p[:4] for p in pool) for w in words)
    return hit / len(words) >= 0.6


def is_right_song(item, song):
    """True only when the video really is THIS song. A wrong video is worse than no video, so this is strict:
    the song title must appear in the video title, and the movie name (or a very exact title match) must back it up.
    Videos titled only in Tamil letters are accepted only when their words appear in this song's lyrics."""
    sn = (item or {}).get("snippet") or {}
    vtitle = _html.unescape(sn.get("title") or "")
    chan = _html.unescape(sn.get("channelTitle") or "")
    desc = _html.unescape(sn.get("description") or "")
    low = vtitle.lower()
    if is_bad_title(low, ((song or {}).get("title") or "") + " " + ((song or {}).get("movie") or "")):
        # scene, sneak peek, climax, teaser, trailer, cover...
        return False
    want = (song or {}).get("title") or ""
    latin = re.sub(r"[^A-Za-z0-9]", "", vtitle)
    if len(latin) < 4:                                    # title is (almost) all Tamil letters
        return tamil_title_matches(vtitle, (song or {}).get("tamil_head", ""))
    songish = bool(_SONG_WORDS.search(low)) or any(l in chan.lower() for l in _LABELS) \
        or bool(re.search(r"\bsongs?\b|\blyric", desc.lower()))
    if not songish:                                       # must LOOK like a song upload, not just carry the movie's name
        return False
    tf = title_fit(want, vtitle)
    movie = (song or {}).get("movie") or ""
    mv_tokens = [t for t in _tokens(movie) if len(t) > 2]
    haystack = low + " " + desc.lower() + " " + chan.lower()
    movie_ok = bool(mv_tokens) and (phon(movie) in phon(haystack) or all(t in haystack for t in mv_tokens))
    if len(phon(want)) < 5:                               # very short names ("Hey", "Bro"): need movie AND the word
        return tf >= 1.0 and movie_ok
    return tf >= 0.88 or (tf >= 0.72 and movie_ok)


def _call(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _http_reason(e):
    try:
        body = e.read().decode("utf-8", "ignore")
    except Exception:
        body = ""
    if "quotaExceeded" in body or "rateLimitExceeded" in body:
        return "quota"
    if e.code in (400, 401, 403) and ("keyInvalid" in body or "API key" in body or "accessNotConfigured" in body):
        return "key"
    return "error"


def _seconds(iso):
    """'PT4M22S' -> 262. None when unknown."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


def _playable(api_key, ids, region, timeout):
    """Asks YouTube (1 quota unit) which of these videos really play here: public, embeddable, not blocked in `region`.
    If YouTube cannot tell us, nothing is filtered out (the page still tries the next video when one fails)."""
    params = urllib.parse.urlencode({"part": "status,contentDetails", "id": ",".join(ids), "key": api_key})
    try:
        data = _call(f"https://www.googleapis.com/youtube/v3/videos?{params}", timeout)
    except Exception:
        return ids
    ok, seen = set(), False
    for it in data.get("items", []):
        vid = (it or {}).get("id")
        if not isinstance(vid, str):
            continue
        seen = True
        st, cd = it.get("status") or {}, it.get("contentDetails") or {}
        rr = cd.get("regionRestriction") or {}
        if st.get("embeddable") is False or st.get("privacyStatus", "public") != "public":
            continue
        if st.get("uploadStatus", "processed") != "processed":
            continue
        secs = _seconds(cd.get("duration"))
        if secs is not None and not (75 <= secs <= 720):      # songs are ~2-9 min; scenes, trailers and full movies are not
            continue
        if region and region in (rr.get("blocked") or []):
            continue
        if region and rr.get("allowed") is not None and region not in rr["allowed"]:
            continue
        ok.add(vid)
    return [v for v in ids if v in ok] if seen else ids


def search(api_key, query, max_results=10, timeout=6, region="IN", song=None):
    """Searches YouTube for embeddable videos, keeps the ones that really play in `region`, best (official) first.

    Returns (video_ids, reason). reason is '' on success, 'quota' when the daily API limit is used up,
    'key' when the key is rejected, and 'error' for anything else (network down, bad response...).
    """
    p = {"part": "snippet", "type": "video", "videoEmbeddable": "true", "videoSyndicated": "true",
         "videoCategoryId": "10", "relevanceLanguage": "ta", "maxResults": max_results, "key": api_key, "q": query}
    if region:
        p["regionCode"] = region
    try:
        items = _call(f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(p)}", timeout).get("items", [])
    except urllib.error.HTTPError as e:
        return [], _http_reason(e)
    except Exception:
        return [], "error"
    good = [(i, it) for i, it in enumerate(items) if is_right_song(it, song)] if song else list(enumerate(items))
    ranked = sorted(good, key=lambda t: (-score(t[1], song), t[0]))     # stable: ties keep YouTube's order
    ids = []
    for _, it in ranked:
        vid = ((it or {}).get("id") or {}).get("videoId", "")
        if VIDEO_ID_RE.match(vid or "") and vid not in ids:
            ids.append(vid)
    if ids:
        ids = _playable(api_key, ids, region, timeout)
    return ids[:10], ""


def alt_queries_for(song):
    t, m = song["title"], song.get("movie", "")
    return [f"{t} {m} lyric video".strip(), f"{t} {m} full video song".strip()]


def search_song(api_key, song, region="IN", timeout=6, alt=False, exclude=()):
    """Looks for THIS song: first '<title> <movie> official tamil song', then (only if nothing matched) a plainer query.
    Returns (video_ids, reason) like search()."""
    skip = set(exclude)
    for q in (alt_queries_for(song) if alt else queries_for(song)[:1]):      # 1 search = 100 of the 10,000 daily units
        ids, reason = search(api_key, q, region=region, song=song, timeout=timeout)
        ids = [v for v in ids if v not in skip]
        if ids or reason:
            return ids, reason
    return [], ""


def query_for(song):
    return f"{song['title']} {song['movie']} official tamil song".strip()


def queries_for(song):
    t, m = song["title"], song.get("movie", "")
    y = song.get("year") or ""
    return [f"{t} {m} official tamil song".strip(), f"{t} {m} {y} song".strip()]


class VideoIndex:
    """Local list of songs from official label channels (data/video_index.csv, built by tools/build_video_index.py).
    Finding a song here costs ZERO YouTube quota, so the daily search limit stops mattering for the songs it covers."""

    def __init__(self, path):
        self.path = Path(path)
        self._stamp = None
        self._rows = []            # (phonetic title, snippet dict, video id)
        self._blob = ""            # all phonetic titles in one string: a very fast first check

    def _load(self):
        rows = []
        if self.path.exists():
            with open(self.path, newline="", encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    vid = clean_video_id(r.get("video_id"))
                    title = (r.get("title") or "").strip()
                    if vid and title:
                        rows.append((phon(title), {"snippet": {"title": title, "channelTitle": r.get("channel") or "",
                                                               "description": ""}}, vid))
        self._rows = rows
        self._blob = "|".join(r[0] for r in rows)

    def _refresh(self):
        try:
            st = self.path.stat()
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        if sig != self._stamp:
            self._load()
            self._stamp = sig

    def count(self):
        self._refresh()
        return len(self._rows)

    def find(self, song, exclude=()):
        """Video ids in the index that really are this song (best first)."""
        self._refresh()
        key = phon(song.get("title"))
        if len(key) < 3 or not self._rows or key not in self._blob:
            return []
        skip = set(exclude)
        hits = [(it, vid) for ph, it, vid in self._rows if key in ph and vid not in skip and is_right_song(it, song)]
        hits.sort(key=lambda t: -score(t[0], song))
        out = []
        for _, vid in hits:
            if vid not in out:
                out.append(vid)
        return out[:6]
