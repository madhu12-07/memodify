#!/usr/bin/env python3
"""Build the app's song library from the Tamil lyrics dataset (Tamil_lyrics_v1.csv).

The dataset has lyrics but NO mood labels, so moods are *estimated from the lyrics*:

  1. A hand-written Tamil/Tanglish keyword lexicon gives each song a first guess.
  2. Songs with a clear guess are used to train a small text classifier
     (TF-IDF + logistic regression) which then scores every song, so the model
     learns extra words that go with each mood.
  3. data/curated_seed.csv (songs whose mood was set by hand) is used to MEASURE
     accuracy, and those songs keep their hand-set mood in the final file.

Outputs (these are what the app loads - the big CSV is not needed at run time):
  data/songs.csv    one row per song: title, movie, year, mood, valence, energy, ...
  data/lyrics.db    SQLite with the Tamil + English lyrics (read on demand)

Usage:
  pip install -r tools/requirements-build.txt
  python tools/build_dataset.py --input path/to/Tamil_lyrics_v1.csv
"""
import argparse
import csv
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from moods import MOODS, VALENCE_ENERGY  # noqa: E402

csv.field_size_limit(10 ** 9)
MOOD_LIST = list(MOODS)

# --------------------------------------------------------------------------
# 1. Keyword lexicon.  Tamil stems are matched at the START of a word, so
#    inflections (காதலி, காதலன், காதலில்...) are caught but mid-word accidents are not.
# --------------------------------------------------------------------------
TAMIL = {
    "sad": """கண்ணீர் அழு அழுகை சோக துயர வலி பிரிவு பிரிந்த பிரிய தனிமை தனியே தனியாக தவி ஏக்க
        கவலை வேதனை துரோக ஏமாற்ற காயம் மரண இறந்த இழந்த இழப்ப நினைவுகள் ஞாபக விதி கண்ணீ
        தவிப்ப நொந்த வாடு வாடி உருக உடைந்த கலங்க கலங்கி இருள் பாவம் சாபம் அனாதை""",
    "romantic": """காதல் காதலி காதலன் கண்ணே கண்மணி முத்த இதழ் உயிரே அன்பே அழகே அழகி நிலா வெண்ணிலா
        தழுவ அணை மயங்க மோகம் விழி தேவதை பெண்ணே பூவே ராசாத்தி கொஞ்ச
        கனவே கண்ணா கண்ணன் ராதை வெட்க நாணம் மஞ்சள் தாலி கல்யாண
        மச்சான் மாமா மாமன் அத்தை ஜோடி """,
    "happy": """சிரி சிரிப்பு மகிழ்ச்சி சந்தோஷ சந்தோச இன்ப கொண்டாட்ட கொண்டாடு திருவிழா கும்மாள வாழ்த்து
        ஜாலி கலகல மகிழ் குதூகல உற்சாக பண்டிகை பொங்கல் தீபாவளி வாழ்க வாழ்வே வசந்த நட்பு நண்பா
        நண்பன் தோழ கூட்டாளி பாடு பாட்டு கலாட்டா சிரிக்க ஹாப்பி""",
    "energetic": """ஆட்டம் ஆடு ஆடலாம் குத்து டான்ஸ் தட்டு மாஸ் வெற்றி ஜெயி வேகம் கலக்கு தூள் அதிரடி
        ராக் கெத்து பறக்க பற திமிர் துள்ளு துள்ள அடிடா அடிச்சு தெறி தெறிக்க ஓடு பாய் எழுந்து எழு
        நிமிர் விளையாட்டு விளையாடு சும்மா பட்டய கிளப்பு பார்ட்டி கானா""",
    "angry": """கோபம் கோப ஆத்திர சீற்ற சீறு கொல்ல கொலை வெட்டு ரத்த இரத்த போர் சண்டை பகை எதிரி
        அழிக்க அழிவு துரோகி வெறி எரி நெருப்பு தீயா ஆவேச புயல் இடி மிரட்ட துப்பாக்கி அடிமை
        புரட்சி போராட்ட சவால் ஆணவ சீண்டாத எச்சரிக்க கொழுத்து கொதி""",
    "calm": """அமைதி தென்றல் காற்று நதி ஆறு மழை மலர் பூக்க இரவு தாலாட்டு தூங்கு உறங்கு கடவுள் இறை
        முருகா சாமி பக்தி இயற்கை மலை வானம் நிலவு மெல்ல மெதுவாக அருவி பறவை குயில் கிளி
        அம்மா தெய்வ ஆண்டவ இறைவ கோயில் திருப்பு வணங்க பாதம் அருள் ஞானம் ஆன்மா சாந்தி
        மௌனம் மௌன நிம்மதி நிழல் தோப்பு வயல் கிராம""",
}
ENGLISH = {  # Tanglish spelling varies a lot, so these are loose regex stems
    "sad": r"kann?eer|sogam|azhu|azha?kai|pirivu|piriy|thani(mai|yaa|ye)|thavi|ekkam|kavalai|vethanai|"
           r"thurogam|yemaat|maranam|ilanth|ninaivu|vidhi|vaadi|urugi|kalang|anaathai|\bvali\b|\bpaavam",
    "romantic": r"k[au]+a?dh?[ai]*l\b|k[au]+a?dh?[ai]*l[ia]|kanne\b|kanmani|mu[th]+am|uyire|anbe|azhage|nilave|"
                r"vennila|thazhuv|mayang|moham|devathai|penne|poove|"
                r"nenjae|kanna\b|raadhai|nanam|veatk|mach+an|maamaa|jodi",
    "happy": r"sirip|santhosh|magizh|inbam|kondaat|thiruvizha|kummaal|vaazhthu|jolly|kalakal|kuthoogal|"
             r"urchaag|pongal|diwali|vasantham|natpu|nanba\b|thozha|kalaatta|happy|celebrat",
    "energetic": r"aatt?am|aadu|aadalaam|kuth+u|dance|thattu|\bmass\b|vetri|jeyi|vegam|kalakku|thool|athiradi|"
                 r"rock|kethu|parakka|thimir|thullu|thull|adida|therika|theri\b|ooodu|vilaiyaad|party|gaana|dj\b",
    "angry": r"kobam|kopam|aaththir|seera|seeru|kolla|kolai|vettu|ratham|\bpor\b|sandai|pagai|ethiri|azhikka|"
             r"azhivu|veri\b|neruppu|aavesh|puyal|idi\b|mirat|thuppaakki|adimai|puratchi|porattam|saval|aanavam",
    "calm": r"amaidhi|thendral|kaatru|nadhi|aaru\b|mazhai|malar|pookk|iravu|thaalaatt|thoongu|urangu|kadavul|"
            r"murug|saami|bhakthi|iyarkai|malai\b|vaanam|nilavu|mella|methuvaa|aruvi|paravai|kuyil|kili\b|"
            r"amma\b|deivam|aandavan|kovil|aruL|gnaanam|saanthi|mounam|nimmathi|nizhal|thoppu|vayal",
}


def compile_lexicon():
    tam = {}
    for mood, words in TAMIL.items():
        stems = sorted({w for w in words.split()}, key=len, reverse=True)
        tam[mood] = re.compile(r"(?<![஀-௿])(?:" + "|".join(map(re.escape, stems)) + ")")
    eng = {m: re.compile(p, re.I) for m, p in ENGLISH.items()}
    return tam, eng


TAM_RE, ENG_RE = compile_lexicon()


def lexicon_scores(tamil, english):
    """Return {mood: score}; score = hits per sqrt(word count) so long songs don't always win."""
    n = max(len(tamil.split()), 20)
    out = {}
    for m in MOOD_LIST:
        hits = len(TAM_RE[m].findall(tamil)) + 0.6 * len(ENG_RE[m].findall(english))
        out[m] = hits / math.sqrt(n)
    return out


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def norm_key(s):
    s = re.sub(r"song lyrics?", "", s or "", flags=re.I)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean_title(s):
    s = re.sub(r"\s*[-–]?\s*song lyrics?\s*$", "", (s or "").strip(), flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"^[\s.\-–_]+", "", s)       # e.g. ". Yedhukkaga Enna Neeyum"


def clean_lyrics(s):
    s = (s or "").replace("\r", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" ?\n ?", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def load(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", newline="")))
    best = {}
    skipped_short = 0
    for r in rows:
        title = clean_title(r.get("song_name"))
        tamil = clean_lyrics(r.get("lyrics_tamil"))
        english = clean_lyrics(r.get("lyrics_english"))
        if not title or len(tamil) < 120:
            skipped_short += 1
            continue
        movie = re.sub(r"\s+", " ", (r.get("movie") or "").strip())
        try:
            year = int(str(r.get("year") or "").strip()[:4])
            if not 1930 <= year <= 2030:
                year = None
        except ValueError:
            year = None
        rec = {
            "title": title, "movie": movie, "year": year,
            "music_director": (r.get("music_director") or "").strip(),
            "lyricist": (r.get("lyricist") or "").strip(),
            "link": (r.get("link") or "").strip(),
            "tamil": tamil, "english": english,
        }
        key = (norm_key(title), norm_key(movie))
        if key not in best or len(tamil) > len(best[key]["tamil"]):
            best[key] = rec
    songs = sorted(best.values(), key=lambda s: (s["title"].lower(), s["movie"].lower()))
    return songs, len(rows), skipped_short


def curated_labels(path):
    """{title_key: [(movie_key, mood), ...]}"""
    out = {}
    if not Path(path).exists():
        return out
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        out.setdefault(norm_key(r["title"]), []).append((norm_key(r.get("movie")), r["mood"].strip().lower()))
    return out


def curated_mood(cur, title_key, movie_key):
    """Hand label for this song, or None. Title must match and the movie must look similar
    (so a different song with the same title is not mislabelled)."""
    import difflib
    for mk, mood in cur.get(title_key, []):
        if not mk or difflib.SequenceMatcher(None, mk, movie_key).ratio() >= 0.6 or mk in movie_key or movie_key in mk:
            return mood
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-dir", default=str(ROOT / "data"))
    ap.add_argument("--seed", default=str(ROOT / "data" / "curated_seed.csv"))
    args = ap.parse_args()

    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    songs, total, skipped = load(args.input)
    print(f"Read {total} rows -> {len(songs)} unique usable songs ({skipped} too short/blank, rest duplicates)")

    # ---- step 1: lexicon ----
    lex = np.array([[lexicon_scores(s["tamil"], s["english"])[m] for m in MOOD_LIST] for s in songs])
    raw_top = lex.max(axis=1)
    # compare every mood against its own typical level, otherwise very common words
    # (love-words) make 'romantic' win almost everywhere
    z = (lex - lex.mean(axis=0)) / (lex.std(axis=0) + 1e-9)
    order = np.sort(z, axis=1)
    top, second = order[:, -1], order[:, -2]
    guess = z.argmax(axis=1)
    confident = (top >= 1.0) & (top - second >= 0.5) & (raw_top > 0)
    print(f"Lexicon is confident for {confident.sum()} songs ({confident.mean():.0%}); "
          f"no keyword evidence at all for {(raw_top == 0).sum()}")

    # ---- step 2: classifier trained on the confident songs ----
    docs = [s["tamil"] + "\n" + s["english"].lower() for s in songs]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=8, max_df=0.6,
                          sublinear_tf=True, max_features=60000)
    X = vec.fit_transform(docs)
    clf = LogisticRegression(max_iter=600, C=4.0, class_weight="balanced")
    clf.fit(X[confident], guess[confident])
    proba_clf = np.zeros((len(songs), len(MOOD_LIST)))
    classes = [MOOD_LIST[i] for i in clf.classes_]
    P = clf.predict_proba(X)
    for j, m in enumerate(classes):
        proba_clf[:, MOOD_LIST.index(m)] = P[:, j]

    # ---- step 3: blend lexicon evidence + classifier ----
    e = np.exp(z - z.max(axis=1, keepdims=True))
    lex_soft = e / e.sum(axis=1, keepdims=True)
    has_words = (lex.sum(axis=1, keepdims=True) > 0)
    proba = 0.5 * proba_clf + 0.5 * np.where(has_words, lex_soft, proba_clf)
    proba = proba / proba.sum(axis=1, keepdims=True)

    mood_idx = proba.argmax(axis=1)

    # ---- step 4: measure accuracy on hand-labelled songs, then let them override ----
    cur = curated_labels(args.seed)
    keys = [norm_key(s["title"]) for s in songs]
    labels = [curated_mood(cur, k, norm_key(songs[i]["movie"])) for i, k in enumerate(keys)]
    uniq = [(i, m) for i, m in enumerate(labels) if m]
    if uniq:
        ok = sum(MOOD_LIST[mood_idx[i]] == m for i, m in uniq)
        lex_ok = sum(MOOD_LIST[guess[i]] == m for i, m in uniq)
        # "valence side" is what the Mood Journey really needs: low (sad/angry) vs high (happy/energetic/romantic)
        side = lambda m: VALENCE_ENERGY[m][0] >= 0.5
        side_ok = sum(side(MOOD_LIST[mood_idx[i]]) == side(m) for i, m in uniq)
        print(f"\nAccuracy check on {len(uniq)} hand-labelled songs found in the dataset:")
        print(f"  exact mood (6 classes): {ok}/{len(uniq)} = {ok / len(uniq):.0%}   (random guessing = 17%)")
        print(f"  positive-vs-negative feeling: {side_ok}/{len(uniq)} = {side_ok / len(uniq):.0%}")
        print(f"  (lexicon alone, exact mood: {lex_ok}/{len(uniq)} = {lex_ok / len(uniq):.0%})")
        report = {"n": len(uniq), "exact": ok / len(uniq), "side": side_ok / len(uniq)}
    else:
        report = None
    curated_flag = np.zeros(len(songs), dtype=bool)
    for i, m in uniq:
        mood_idx[i] = MOOD_LIST.index(m)
        proba[i] = 0.05 / (len(MOOD_LIST) - 1)
        proba[i, mood_idx[i]] = 0.95
        curated_flag[i] = True

    # ---- write outputs ----
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    val = np.array([VALENCE_ENERGY[m][0] for m in MOOD_LIST])
    ene = np.array([VALENCE_ENERGY[m][1] for m in MOOD_LIST])
    cols = ["id", "title", "movie", "year", "music_director", "lyricist", "mood", "confidence",
            "valence", "energy", "curated", "source_link"]
    with open(out / "songs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i, s in enumerate(songs):
            w.writerow([i + 1, s["title"], s["movie"], s["year"] or "", s["music_director"], s["lyricist"],
                        MOOD_LIST[mood_idx[i]], f"{proba[i, mood_idx[i]]:.3f}",
                        f"{(proba[i] * val).sum():.3f}", f"{(proba[i] * ene).sum():.3f}",
                        int(curated_flag[i]), s["link"]])
    db_path = out / "lyrics.db"
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE lyrics (id INTEGER PRIMARY KEY, tamil TEXT, english TEXT)")
    con.executemany("INSERT INTO lyrics VALUES (?,?,?)", [(i + 1, s["tamil"], s["english"]) for i, s in enumerate(songs)])
    con.commit()
    con.execute("VACUUM")
    con.close()

    dist = Counter(MOOD_LIST[i] for i in mood_idx)
    print("\nSongs per mood:", dict(dist))
    print(f"Wrote {out / 'songs.csv'} and {db_path} ({db_path.stat().st_size / 1e6:.1f} MB)")
    if report:
        (out / "mood_model_report.txt").write_text(
            f"Mood labels are ESTIMATED from lyrics.\n"
            f"Checked on {report['n']} hand-labelled songs: exact mood {report['exact']:.0%}, "
            f"positive/negative feeling {report['side']:.0%}.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
