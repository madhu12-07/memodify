"""Mood definitions, quiz questions, emoji map, face-emotion map and Mood Journey paths.

All the "which mood is this?" logic lives here on the server so the
front-end cannot be tampered with and the logic is easy to unit-test.

The app UI is English. Tamil is used only in the quiz (every question and
answer is shown in Tamil + English).
"""

# ---------------------------------------------------------------- moods
MOODS = {
    "happy":     {"label": "Happy",     "emoji": "😄", "color": "#E8C27A", "msg": "Great vibes! Songs to match your joy."},
    "sad":       {"label": "Sad",       "emoji": "😢", "color": "#5BA8C9", "msg": "It's okay. Let the music keep you company."},
    "calm":      {"label": "Calm",      "emoji": "😌", "color": "#4FBFA8", "msg": "Soft songs for a peaceful mind."},
    "energetic": {"label": "Energetic", "emoji": "🔥", "color": "#E8946A", "msg": "Full energy! Turn these up."},
    "romantic":  {"label": "Romantic",  "emoji": "😍", "color": "#D9788C", "msg": "In a lovely mood? These are made for you."},
    "angry":     {"label": "Angry",     "emoji": "😠", "color": "#C8544F", "msg": "Let the music take the anger out."},
}

# Rough position of each mood on a "how positive" (valence) x "how intense" (energy) map, 0..1.
# The Mood Journey uses valence for its curve; the dataset builder uses both.
VALENCE_ENERGY = {
    "sad": (0.10, 0.20), "angry": (0.20, 0.90), "calm": (0.55, 0.15),
    "romantic": (0.70, 0.40), "happy": (0.90, 0.70), "energetic": (0.80, 0.95),
}

# ------------------------------------------------------------ age groups
# Each age group is matched with the songs of the years it grew up with (the dataset covers 1954-2026).
# `years` is (first, last) release year. If a mood has too few songs in that range the range is widened a little.
AGE_GROUPS = {
    "teen":   {"label": "Under 18", "emoji": "🎧", "years": (2015, 2026), "blurb": "Latest hits"},
    "young":  {"label": "18 - 25",  "emoji": "🎤", "years": (2012, 2026), "blurb": "Fresh and trending"},
    "adult":  {"label": "26 - 35",  "emoji": "🎸", "years": (2005, 2016), "blurb": "Songs you grew up with"},
    "mid":    {"label": "36 - 50",  "emoji": "🎹", "years": (1994, 2008), "blurb": "Golden 90s and 2000s"},
    "senior": {"label": "51 - 65",  "emoji": "🪕", "years": (1978, 1995), "blurb": "Classic melodies"},
    "elder":  {"label": "65 +",     "emoji": "📻", "years": (1954, 1985), "blurb": "Timeless old songs"},
}
AGE_ORDER = list(AGE_GROUPS)


def age_years(age):
    """(first, last) release year for an age-group key, or None for 'all years' / unknown keys."""
    g = AGE_GROUPS.get(age)
    return g["years"] if g else None


# ------------------------------------------------------- face -> mood
# face-api.js returns: neutral, happy, sad, angry, fearful, disgusted, surprised
FACE_TO_MOOD = {
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "surprised": "energetic",
    "fearful": "calm",      # soothing songs for a stressed face
    "disgusted": "angry",
    "neutral": "calm",
}

# ------------------------------------------------------------ emojis
# One emoji per emotion the face scanner can recognise (same 7 as face-api.js), so the
# Emoji picker and the Face page speak the same language.
FACE_EMOJI = {
    "neutral": "😐", "happy": "😄", "sad": "😢", "angry": "😠",
    "fearful": "😨", "disgusted": "🤢", "surprised": "😲",
}
FACE_LABELS = {
    "neutral": "Neutral", "happy": "Happy", "sad": "Sad", "angry": "Angry",
    "fearful": "Fearful", "disgusted": "Disgusted", "surprised": "Surprised",
}
EMOJI_TO_MOOD = {FACE_EMOJI[k]: FACE_TO_MOOD[k] for k in FACE_EMOJI}
EMOJI_LABELS = {FACE_EMOJI[k]: FACE_LABELS[k] for k in FACE_EMOJI}

# -------------------------------------------------------------- quiz
# Each option adds points to one or more moods. The server sums them up.
QUIZ = [
    {
        "id": "q1",
        "ta": "இன்னைக்கு உங்க நாள் எப்படி இருந்துச்சு?",
        "en": "How was your day today?",
        "options": [
            {"ta": "செம சூப்பர்!", "en": "Awesome!", "score": {"happy": 2, "energetic": 1}},
            {"ta": "பரவாயில்ல, அமைதியா போச்சு", "en": "Fine, a peaceful one", "score": {"calm": 2}},
            {"ta": "ரொம்ப கஷ்டமா இருந்துச்சு", "en": "It was really tough", "score": {"sad": 2}},
            {"ta": "எரிச்சலா இருந்துச்சு", "en": "It was irritating", "score": {"angry": 2}},
        ],
    },
    {
        "id": "q2",
        "ta": "இப்போ உங்க மனசுல என்ன ஓடுது?",
        "en": "What is on your mind right now?",
        "options": [
            {"ta": "ஒருத்தர் ஞாபகம் வருது 💭", "en": "Thinking of someone special", "score": {"romantic": 2, "sad": 1}},
            {"ta": "ஒண்ணுமே இல்ல, ரிலாக்ஸ்", "en": "Nothing, just relaxed", "score": {"calm": 2}},
            {"ta": "நிறைய வேலை, டென்ஷன்", "en": "Lots of work and tension", "score": {"angry": 1, "energetic": 1}},
            {"ta": "கொண்டாடணும் போல இருக்கு!", "en": "I feel like celebrating!", "score": {"happy": 2, "energetic": 1}},
        ],
    },
    {
        "id": "q3",
        "ta": "இப்போ என்ன செய்ய ஆசை?",
        "en": "What do you feel like doing now?",
        "options": [
            {"ta": "டான்ஸ் ஆடணும்!", "en": "Dance!", "score": {"energetic": 2, "happy": 1}},
            {"ta": "தனியா உட்கார்ந்து யோசிக்கணும்", "en": "Sit alone and think", "score": {"sad": 1, "calm": 1}},
            {"ta": "நண்பர்களோட வெளிய போகணும்", "en": "Go out with friends", "score": {"happy": 2}},
            {"ta": "யார்கிட்டயாவது மனசு விட்டு பேசணும்", "en": "Pour my heart out to someone", "score": {"romantic": 1, "sad": 1}},
        ],
    },
    {
        "id": "q4",
        "ta": "எந்த மாதிரி இசை இப்போ பிடிக்கும்?",
        "en": "What kind of music do you want now?",
        "options": [
            {"ta": "குத்து / மாஸ் பீட்", "en": "Kuthu / mass beats", "score": {"energetic": 2, "angry": 1}},
            {"ta": "மெல்லிய மெலடி", "en": "Soft melody", "score": {"calm": 2, "romantic": 1}},
            {"ta": "காதல் பாடல்", "en": "Love song", "score": {"romantic": 2}},
            {"ta": "மனசை தொடும் சோக பாடல்", "en": "Heart-touching sad song", "score": {"sad": 2}},
        ],
    },
    {
        "id": "q5",
        "ta": "உங்க எனர்ஜி லெவல் எப்படி?",
        "en": "How is your energy level?",
        "options": [
            {"ta": "சூப்பர் ஹை! 🚀", "en": "Super high!", "score": {"energetic": 2, "happy": 1}},
            {"ta": "மிதமா இருக்கு", "en": "Medium", "score": {"calm": 1, "romantic": 1}},
            {"ta": "ரொம்ப குறைவு", "en": "Very low", "score": {"sad": 1, "calm": 1}},
            {"ta": "கோபத்துல கொதிக்குது", "en": "Boiling with anger", "score": {"angry": 2}},
        ],
    },
]

MOOD_ORDER = ["happy", "energetic", "calm", "romantic", "sad", "angry"]


def mood_from_quiz(answers):
    """answers: list of option indexes (one per question). Returns (mood, scores)
    or raises ValueError if the payload is invalid."""
    if not isinstance(answers, list) or len(answers) != len(QUIZ):
        raise ValueError("Answer every question.")
    scores = {m: 0 for m in MOODS}
    for q, a in zip(QUIZ, answers):
        if not isinstance(a, int) or isinstance(a, bool) or not 0 <= a < len(q["options"]):
            raise ValueError("Invalid answer.")
        for mood, pts in q["options"][a]["score"].items():
            scores[mood] += pts
    best = max(MOOD_ORDER, key=lambda m: (scores[m], -MOOD_ORDER.index(m)))
    return best, scores


def public_quiz():
    """Quiz without the scoring, safe to send to the browser."""
    return [
        {
            "id": q["id"], "ta": q["ta"], "en": q["en"],
            "options": [{"ta": o["ta"], "en": o["en"]} for o in q["options"]],
        }
        for q in QUIZ
    ]


# ------------------------------------------------------ Mood Journey
# The journey starts at the listener's mood and walks, stage by stage, towards a happy mood.
# Stages are equal slices of the chosen time (no analysis happens while listening).
JOURNEY_PATHS = {
    "sad":       ["sad", "calm", "romantic", "happy"],
    "angry":     ["angry", "calm", "romantic", "happy"],
    "calm":      ["calm", "romantic", "happy"],
    "romantic":  ["romantic", "happy"],
    "happy":     ["happy", "energetic"],
    "energetic": ["energetic", "happy"],
}
JOURNEY_MINUTES = (20, 30, 45, 60)       # shortest = 4 stages x 5 min, so every stage has room for at least one song
SONG_SLOT_SECONDS = 210          # how long one song "slot" lasts when no audio player is available


def journey_plan(start_mood, minutes):
    """Return the stage plan: [{mood, start, end}] in seconds. Raises ValueError on bad input."""
    if start_mood not in JOURNEY_PATHS:
        raise ValueError("Unknown mood.")
    if minutes not in JOURNEY_MINUTES:
        raise ValueError("Choose 20, 30, 45 or 60 minutes.")
    path = JOURNEY_PATHS[start_mood]
    total = minutes * 60
    step = total / len(path)
    return [{"mood": m, "start": round(i * step), "end": round((i + 1) * step)} for i, m in enumerate(path)]
