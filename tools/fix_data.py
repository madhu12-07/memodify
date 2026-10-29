#!/usr/bin/env python3
"""Repairs title / lyrics mix-ups in data/songs.csv + data/lyrics.db (safe to run again).

What it fixes
  1. LYRICS SWAPPED BETWEEN SONGS of the same movie (the source website had them swapped, e.g. the lyrics saved under
     "Dil Dil Dil Manadhil" were really "Kuzhaloothum Kannanukku"). A song whose own lyrics do not contain its title,
     while another song of the same movie's lyrics clearly do, gets those lyrics.
  2. WRONG TITLES. The title column sometimes holds the first line of the song, the movie name or a person's name.
     The page address in `source_link` holds the real song name, so it is used when the two clearly disagree.

Originals are copied to data/_backup/ the first time. A readable list of every change goes to data/data_fix_report.txt.
Usage:  python tools/fix_data.py
"""
import csv
import difflib
import re
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GENERIC_SLUGS = {"title-track", "theme", "song", "songs", "lyrics", "audio", "video", "full-song"}
SMALL = {"a", "an", "the", "of", "in", "on", "to", "and", "or", "for", "vs", "ii", "iii"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def phon(s):
    """Rough Tamil-in-English-letters key, so Kuzhaloodhum == Kuzhaloothum and Yaarovai == Yaaro vaai."""
    s = (s or "").lower()
    s = s.replace("zh", "l").replace("’", "").replace("'", "")
    s = re.sub(r"([tdkgcbps])h", r"\1", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    s = re.sub(r"(.)\1+", r"\1", s)
    s = s.replace("dh", "t").replace("d", "t").replace("g", "k").replace("w", "v").replace("b", "p")
    return s


def fit(title, text):
    """0..1: how well the (phonetic) title appears anywhere inside the lyrics text."""
    t = phon(title)
    if len(t) < 4:
        return 1.0                                  # too short to judge, never move lyrics because of it
    body = phon(text)
    if t in body:
        return 1.0
    best, L = 0.0, len(t)
    step = max(1, L // 6)
    for i in range(0, max(1, len(body) - L + 1), step):
        r = difflib.SequenceMatcher(None, t, body[i:i + L]).ratio()
        if r > best:
            best = r
            if best >= 0.9:
                break
    return best


def slug_title(link):
    m = re.search(r"allnewlyrics\.com/([^/]+)/?$", link or "")
    if not m:
        return ""
    slug = m.group(1)
    base = re.sub(r"-?song-lyrics.*$", "", slug)
    if not base or base in GENERIC_SLUGS or re.fullmatch(r"[\d-]+", base):
        return ""
    words = [w for w in base.split("-") if w]
    return " ".join(w.capitalize() if (i == 0 or w not in SMALL) else w for i, w in enumerate(words))


def main():
    src = DATA / "_backup" if (DATA / "_backup" / "songs.csv").exists() else DATA     # always start from the originals
    rows = list(csv.DictReader(open(src / "songs.csv", encoding="utf-8-sig", newline="")))
    cols = list(rows[0].keys())
    con = sqlite3.connect(src / "lyrics.db")
    ly = {i: [t, e] for i, t, e in con.execute("SELECT id, tamil, english FROM lyrics")}
    for r in rows:
        r["_id"] = int(r["id"])
    report = []

    for r in rows:                                   # junk words copied from the website
        clean = re.sub(r"\s*[-–]?\s*song lyrics?\b.*$", "", r["title"], flags=re.I).strip()
        if clean and clean != r["title"]:
            report.append(f"CLEAN  #{r['_id']}: '{r['title']}'  ->  '{clean}'")
            r["title"] = clean

    # ---------- 2. wrong titles (done first so step 1 uses the right names) ----------
    people = {r["music_director"].lower() for r in rows} | {r["lyricist"].lower() for r in rows}
    for r in rows:
        st = slug_title(r["source_link"])
        if not st or norm(st) == norm(r["title"]):
            continue
        sim = difflib.SequenceMatcher(None, phon(r["title"]), phon(st)).ratio()
        is_person = r["title"].lower() in people and norm(r["title"]) != norm(r["movie"])
        is_movie = norm(r["title"]) == norm(r["movie"]) and sim < 0.6
        text = ly[r["_id"]][1] or ""
        title_not_in_lyrics = fit(r["title"], text) < 0.62 and len(text) > 100
        slug_in_lyrics = fit(st, text) >= 0.85
        if is_person or ((is_movie or title_not_in_lyrics) and sim < 0.6 and slug_in_lyrics):
            report.append(f"TITLE  #{r['_id']} ({r['movie']}): '{r['title']}'  ->  '{st}'")
            r["title"] = st

    # ---------- 1. swapped lyrics inside one movie ----------
    by_movie = defaultdict(list)
    for r in rows:
        by_movie[norm(r["movie"])].append(r)
    for group in by_movie.values():
        if len(group) < 2 or len(group) > 40:
            continue
        have = [r for r in group if len((ly[r["_id"]][0] or "") + (ly[r["_id"]][1] or "")) > 100]
        own = {r["_id"]: max(fit(r["title"], ly[r["_id"]][1]), fit(r["title"], ly[r["_id"]][0])) for r in have}
        wrong = [r for r in have if own[r["_id"]] < 0.62]
        if not wrong:
            continue
        taken, moves = set(), {}
        for r in wrong:
            cands = []
            for o in have:
                if o["_id"] == r["_id"] or o["_id"] in taken or o["_id"] not in {w["_id"] for w in wrong}:
                    continue
                sc = fit(r["title"], ly[o["_id"]][1])
                if sc >= 0.85:
                    cands.append((sc, o["_id"]))
            if cands:
                sc, oid = max(cands)
                moves[r["_id"]] = oid
                taken.add(oid)
        if moves:
            snapshot = {k: list(v) for k, v in ly.items()}
            for rid, oid in moves.items():
                ly[rid] = snapshot[oid]
                report.append(f"LYRICS #{rid} gets the lyrics that were saved under #{oid}")

    # ---------- write ----------
    for name in ("songs.csv", "lyrics.db"):
        bak = DATA / "_backup" / name
        if not bak.exists():
            bak.parent.mkdir(exist_ok=True)
            shutil.copy(DATA / name, bak)
    with open(DATA / "songs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    con.close()                                       # never write into the backup/original database
    out_db = DATA / "lyrics.db"
    if out_db.exists():
        out_db.unlink()
    new = sqlite3.connect(out_db)
    new.execute("CREATE TABLE lyrics (id INTEGER PRIMARY KEY, tamil TEXT, english TEXT)")
    new.executemany("INSERT INTO lyrics VALUES (?,?,?)", [(i, t, e) for i, (t, e) in sorted(ly.items())])
    new.commit()
    new.execute("VACUUM")
    new.close()
    (DATA / "data_fix_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"{len(report)} fixes written. See data/data_fix_report.txt")


if __name__ == "__main__":
    main()
