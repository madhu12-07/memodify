"""Memodify - Tamil Mood Music app (Flask backend)."""
import os
import random
import time
import re
import secrets
from functools import wraps
from pathlib import Path

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import db as dbmod
import youtube
from moods import (AGE_GROUPS, AGE_ORDER, EMOJI_LABELS, EMOJI_TO_MOOD, FACE_TO_MOOD, JOURNEY_MINUTES,
                   JOURNEY_PATHS, MOODS, MOOD_ORDER, age_years, SONG_SLOT_SECONDS, VALENCE_ENERGY,
                   journey_plan, mood_from_quiz, public_quiz)
from recommender import SongLibrary

BASE_DIR = Path(__file__).resolve().parent
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_env_file(path):
    """Minimal .env reader so you don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def create_app(test_config=None):
    load_env_file(BASE_DIR / ".env")
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(exist_ok=True)

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        key_file = Path(app.instance_path) / "secret_key"
        if not key_file.exists():
            key_file.write_text(secrets.token_hex(32))
        secret = key_file.read_text().strip()

    app.config.update(
        SECRET_KEY=secret,
        DATABASE=os.path.join(app.instance_path, "manaisai.db"),
        SONGS_FILE=os.environ.get("SONGS_FILE", str(BASE_DIR / "data" / "songs.csv")),
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID", ""),
        YOUTUBE_API_KEY=os.environ.get("YOUTUBE_API_KEY", ""),
        YOUTUBE_IDS_FILE=os.environ.get("YOUTUBE_IDS_FILE", str(BASE_DIR / "data" / "youtube_ids.csv")),
        YOUTUBE_REGION=os.environ.get("YOUTUBE_REGION", "IN"),
        CURATED_SEED_FILE=str(BASE_DIR / "data" / "curated_seed.csv"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("APP_ENV", "").lower() == "production",
        MAX_CONTENT_LENGTH=64 * 1024,
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
    )
    if test_config:
        app.config.update(test_config)
    if os.environ.get("APP_ENV", "").lower() == "production":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # correct client IP + https behind Render/Railway/nginx

    dbmod.init_db(app)
    app.teardown_appcontext(dbmod.close_db)
    library = SongLibrary(app.config["SONGS_FILE"])
    app.library = library
    known_ids = youtube.KnownIds(app.config["YOUTUBE_IDS_FILE"], app.config["CURATED_SEED_FILE"])
    app.known_ids = known_ids
    video_index = youtube.VideoIndex(BASE_DIR / "data" / "video_index.csv")
    app.video_index = video_index
    quota = app.quota = {"until": 0.0}      # when YouTube says the daily limit is used up, stop asking for a while (and prefer known songs)
    no_result = set()          # songs the API found nothing for (not asked again until restart: saves quota)

    def youtube_enabled():
        return bool(app.config["YOUTUBE_API_KEY"]) or known_ids.count() > 0 or video_index.count() > 0

    def db():
        return dbmod.get_db(app)

    # ------------------------------------------------------------ helpers
    def current_user():
        uid = session.get("uid")
        if not uid:
            return None
        return db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    def login_required(view):
        @wraps(view)
        def wrapper(*a, **kw):
            user = current_user()
            if user is None:
                session.clear()
                if request.path.startswith("/api/"):
                    return jsonify(error="Please log in first."), 401
                return redirect(url_for("login_page"))
            return view(user, *a, **kw)
        return wrapper

    def start_session(user_id):
        session.clear()
        session["uid"] = user_id
        session.permanent = True

    def err(msg, code=400):
        return jsonify(error=msg), code

    def current_age(explicit=None):
        """Valid age-group key from `explicit` (e.g. the URL) or the session, else None."""
        for cand in (explicit, session.get("age")):
            if cand in AGE_GROUPS:
                return cand
        return None

    def need_age(view):
        """Face / Quiz / Emoji pages need an age group first; send people to the Detect page to pick one."""
        @wraps(view)
        def wrapper(user, *a, **kw):
            if not current_age():
                return redirect(url_for("detect_page"))
            return view(user, *a, **kw)
        return wrapper

    def cached_ids(song):
        row = db().execute("SELECT video_id FROM yt_cache_v4 WHERE song_key = ?",
                           (youtube.song_key(song["title"], song["movie"]),)).fetchone()
        return youtube.clean_id_list(row["video_id"].split(",")) if row else []

    def has_video(song):
        """True when this song can play WITHOUT a YouTube search (known id, cached id or local index)."""
        return bool(known_ids.get(song["title"], song["movie"]) or cached_ids(song) or video_index.find(song))

    def prefer_playable(songs):
        """While the daily search limit is used up, show songs that can still play first (stable order otherwise)."""
        if time.time() >= quota["until"]:
            return songs
        return sorted(songs, key=lambda s: 0 if has_video(s) else 1)

    def song_json(song, fav_ids=()):
        return {
            "id": song["id"], "title": song["title"], "movie": song["movie"], "year": song["year"],
            "music_director": song["music_director"], "mood": song["mood"],
            "valence": round(song["valence"], 3), "search_url": song["search_url"],
            "source_link": song["source_link"], "favorite": song["id"] in fav_ids,
            "has_lyrics": library.has_lyrics(song["id"]),
        }

    def fav_ids_for(user_id):
        rows = db().execute("SELECT song_id FROM favorites WHERE user_id = ?", (user_id,))
        return {r["song_id"] for r in rows}

    @app.context_processor
    def inject_globals():
        return {"user": current_user(), "MOODS": MOODS}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # camera is needed on our own origin for face detection
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=()")
        return resp

    # -------------------------------------------------------------- pages
    @app.get("/")
    def splash():
        return render_template("splash.html", logged_in=current_user() is not None)

    @app.get("/login")
    def login_page():
        if current_user():
            return redirect(url_for("home"))
        return render_template("login.html", google_client_id=app.config["GOOGLE_CLIENT_ID"])

    @app.get("/home")
    @login_required
    def home(user):
        rows = db().execute(
            "SELECT mood, source, created_at FROM mood_history WHERE user_id = ? "
            "ORDER BY id DESC LIMIT 5", (user["id"],)).fetchall()
        total = db().execute(
            "SELECT COUNT(*) c FROM mood_history WHERE user_id = ?", (user["id"],)).fetchone()["c"]
        top = db().execute(
            "SELECT mood, COUNT(*) c FROM mood_history WHERE user_id = ? "
            "GROUP BY mood ORDER BY c DESC LIMIT 1", (user["id"],)).fetchone()
        favs = db().execute(
            "SELECT COUNT(*) c FROM favorites WHERE user_id = ?", (user["id"],)).fetchone()["c"]
        return render_template("home.html", recent=rows, total=total,
                               top_mood=top["mood"] if top else None, fav_count=favs,
                               total_songs=len(library.songs))

    @app.get("/detect")
    @login_required
    def detect_page(user):
        return render_template("detect.html", ages=AGE_GROUPS, age_order=AGE_ORDER, chosen=current_age())

    @app.get("/face")
    @login_required
    @need_age
    def face_page(user):
        return render_template("face.html")

    @app.get("/quiz")
    @login_required
    @need_age
    def quiz_page(user):
        return render_template("quiz.html")

    @app.get("/emoji")
    @login_required
    @need_age
    def emoji_page(user):
        return render_template("emoji.html")

    @app.get("/results")
    @login_required
    def results_page(user):
        mood = request.args.get("mood", "")
        if mood not in MOODS:
            return redirect(url_for("home"))
        age = current_age(request.args.get("age"))
        return render_template("results.html", mood=mood, info=MOODS[mood], age=age,
                               age_info=AGE_GROUPS.get(age), source=request.args.get("source", ""))

    @app.get("/journey")
    @login_required
    def journey_page(user):
        mood = request.args.get("mood", "")
        if mood not in JOURNEY_PATHS:
            mood = "sad"
        age = current_age()
        return render_template("journey.html", start_mood=mood, age_info=AGE_GROUPS.get(age), minutes_options=JOURNEY_MINUTES,
                               paths=JOURNEY_PATHS, slot_seconds=SONG_SLOT_SECONDS,
                               valence={m: v[0] for m, v in VALENCE_ENERGY.items()})

    @app.get("/history")
    @login_required
    def history_page(user):
        rows = db().execute(
            "SELECT mood, source, created_at FROM mood_history WHERE user_id = ? "
            "ORDER BY id DESC LIMIT 100", (user["id"],)).fetchall()
        counts = {m: 0 for m in MOOD_ORDER}
        for r in rows:
            counts[r["mood"]] += 1
        return render_template("history.html", rows=rows, counts=counts)

    @app.get("/favorites")
    @login_required
    def favorites_page(user):
        ids = [r["song_id"] for r in db().execute(
            "SELECT song_id FROM favorites WHERE user_id = ? ORDER BY id DESC", (user["id"],))]
        songs = [song_json(library.get(i), set(ids)) for i in ids if library.get(i)]
        return render_template("favorites.html", songs=songs)

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    # --------------------------------------------------------------- auth
    @app.get("/api/config")
    def api_config():
        return jsonify(google_client_id=app.config["GOOGLE_CLIENT_ID"],
                       youtube_enabled=youtube_enabled())

    @app.post("/api/signup")
    def api_signup():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        if len(name) < 2:
            return err("Please enter your name (2+ letters).")
        if not EMAIL_RE.match(email):
            return err("Please enter a valid email.")
        if len(password) < 6:
            return err("Password must be at least 6 characters.")
        if db().execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            return err("This email is already registered. Please log in.", 409)
        cur = db().execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name[:60], email, generate_password_hash(password)))
        db().commit()
        start_session(cur.lastrowid)
        return jsonify(ok=True, redirect=url_for("home")), 201

    @app.post("/api/login")
    def api_login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        row = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not row["password_hash"] or not check_password_hash(row["password_hash"], password):
            return err("Wrong email or password.", 401)
        start_session(row["id"])
        return jsonify(ok=True, redirect=url_for("home"))

    def verify_google_token(token):
        """Returns the Google profile dict or raises ValueError."""
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token
        return id_token.verify_oauth2_token(
            token, g_requests.Request(), app.config["GOOGLE_CLIENT_ID"])

    app.verify_google_token = verify_google_token

    @app.post("/api/google")
    def api_google():
        if not app.config["GOOGLE_CLIENT_ID"]:
            return err("Google sign-in is not configured yet. Set GOOGLE_CLIENT_ID in .env.", 503)
        data = request.get_json(silent=True) or {}
        token = data.get("credential")
        if not token or not isinstance(token, str):
            return err("Missing Google credential.")
        try:
            info = app.verify_google_token(token)
        except Exception:
            return err("Google sign-in failed. Please try again.", 401)
        if not info.get("email") or not info.get("email_verified", False):
            return err("Your Google email is not verified.", 401)
        email = info["email"].lower()
        sub = info.get("sub")
        row = db().execute("SELECT * FROM users WHERE google_sub = ? OR email = ?", (sub, email)).fetchone()
        if row is None:
            cur = db().execute(
                "INSERT INTO users (name, email, google_sub, avatar) VALUES (?, ?, ?, ?)",
                ((info.get("name") or email.split("@")[0])[:60], email, sub, info.get("picture")))
            db().commit()
            uid = cur.lastrowid
        else:
            uid = row["id"]
            if not row["google_sub"]:
                db().execute("UPDATE users SET google_sub = ?, avatar = ? WHERE id = ?",
                             (sub, info.get("picture"), uid))
                db().commit()
        start_session(uid)
        return jsonify(ok=True, redirect=url_for("home"))

    # --------------------------------------------------- mood + songs API
    @app.get("/api/quiz")
    @login_required
    def api_quiz(user):
        return jsonify(questions=public_quiz())

    @app.get("/api/emojis")
    @login_required
    def api_emojis(user):
        return jsonify(emojis=[{"emoji": e, "label": EMOJI_LABELS[e]} for e in EMOJI_TO_MOOD])

    @app.post("/api/age")
    @login_required
    def api_age(user):
        data = request.get_json(silent=True) or {}
        age = data.get("age")
        if age not in AGE_GROUPS:
            return err("Please choose one of the age groups.")
        session["age"] = age
        return jsonify(ok=True, age=age, label=AGE_GROUPS[age]["label"])

    @app.post("/api/recommend")
    @login_required
    def api_recommend(user):
        data = request.get_json(silent=True) or {}
        age = current_age()
        if not age:
            return err("Please choose your age group first.", 400)
        source = data.get("source")
        extra = {}
        if source == "face":
            probs = data.get("expressions")
            if not isinstance(probs, dict) or not probs:
                return err("No face expression received.")
            clean = {}
            for k, v in probs.items():
                if k in FACE_TO_MOOD and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1:
                    clean[k] = float(v)
            if not clean:
                return err("Could not read the expression.")
            emotion = max(clean, key=clean.get)
            mood = FACE_TO_MOOD[emotion]
            extra = {"emotion": emotion, "confidence": round(clean[emotion], 3)}
        elif source == "quiz":
            try:
                mood, scores = mood_from_quiz(data.get("answers"))
            except ValueError as e:
                return err(str(e))
            extra = {"scores": scores}
        elif source == "emoji":
            mood = EMOJI_TO_MOOD.get(data.get("emoji"))
            if not mood:
                return err("Unknown emoji.")
        else:
            return err("Unknown source.")
        db().execute("INSERT INTO mood_history (user_id, mood, source) VALUES (?, ?, ?)",
                     (user["id"], mood, source))
        db().commit()
        return jsonify(mood=mood, label=MOODS[mood]["label"], source=source,
                       redirect=url_for("results_page", mood=mood, source=source, age=age), **extra)

    @app.get("/api/songs")
    @login_required
    def api_songs(user):
        mood = request.args.get("mood", "")
        if mood not in MOODS:
            return err("Unknown mood.")
        try:
            exclude = [int(x) for x in request.args.get("exclude", "").split(",") if x]
        except ValueError:
            return err("Bad exclude list.")
        favs = fav_ids_for(user["id"])
        years = age_years(current_age(request.args.get("age")))
        if time.time() < quota["until"]:
            ex = set(exclude)
            fresh = [x for x in library.pool(mood, years=years) if x["id"] not in ex]
            random.shuffle(fresh)
            songs = prefer_playable(fresh)[:8]
            random.shuffle(songs)
        else:
            songs = library.recommend(mood, limit=8, exclude_ids=exclude, years=years)
        return jsonify(mood=mood, songs=[song_json(s, favs) for s in songs])

    @app.post("/api/favorites/<int:song_id>")
    @login_required
    def api_toggle_favorite(user, song_id):
        if not library.get(song_id):
            return err("Song not found.", 404)
        row = db().execute("SELECT id FROM favorites WHERE user_id = ? AND song_id = ?",
                           (user["id"], song_id)).fetchone()
        if row:
            db().execute("DELETE FROM favorites WHERE id = ?", (row["id"],))
            fav = False
        else:
            db().execute("INSERT INTO favorites (user_id, song_id) VALUES (?, ?)",
                         (user["id"], song_id))
            fav = True
        db().commit()
        return jsonify(favorite=fav)

    @app.get("/api/lyrics/<int:song_id>")
    @login_required
    def api_lyrics(user, song_id):
        song = library.get(song_id)
        if not song:
            return err("Song not found.", 404)
        text = library.lyrics(song_id) or {"tamil": "", "english": ""}
        return jsonify(id=song_id, title=song["title"], movie=song["movie"], **text)

    @app.get("/api/play/<int:song_id>")
    @login_required
    def api_play(user, song_id):
        """In-page playback: returns YouTube video ids the page can put in its embedded player.
        `candidates` is best-first; the page tries the next one when a video refuses to embed."""
        song = library.get(song_id)
        if not song:
            return err("Song not found.", 404)
        out = {"video_id": "", "candidates": [], "search_url": song["search_url"],
               "enabled": youtube_enabled(), "reason": ""}

        def done(ids):
            out["candidates"] = ids
            out["video_id"] = ids[0] if ids else ""
            return jsonify(out)

        if request.args.get("more"):
            # the page asks for ANOTHER version because the saved ones refused to play (e.g. YouTube error 150)
            tried = set(youtube.clean_id_list(request.args.get("exclude", "").split(",")))
            ids = video_index.find(song, exclude=tried)
            reason = ""
            if not ids and not app.config["YOUTUBE_API_KEY"]:
                out["reason"] = "no_key"
                return jsonify(out)
            if not ids and time.time() < quota["until"]:
                out["reason"] = "quota"
                return jsonify(out)
            if not ids:
                head = (library.lyrics(song_id) or {}).get("tamil", "")[:700]
                ids, reason = youtube.search_song(app.config["YOUTUBE_API_KEY"], {**song, "tamil_head": head},
                                                 region=app.config["YOUTUBE_REGION"], alt=True, exclude=tried)
                if reason == "quota":
                    quota["until"] = time.time() + 3600
            out["reason"] = reason or ("" if ids else "not_found")
            out["candidates"], out["video_id"] = ids, (ids[0] if ids else "")
            if ids:
                key = youtube.song_key(song["title"], song["movie"])
                db().execute("INSERT OR REPLACE INTO yt_cache_v4 (song_key, video_id) VALUES (?, ?)", (key, ",".join(ids)))
                db().commit()
            return jsonify(out)

        known = known_ids.get(song["title"], song["movie"])
        if known:
            return done(known)
        key = youtube.song_key(song["title"], song["movie"])
        row = db().execute("SELECT video_id FROM yt_cache_v4 WHERE song_key = ?", (key,)).fetchone()
        if row:
            cached = youtube.clean_id_list(row["video_id"].split(","))
            if cached:
                return done(cached)
        indexed = video_index.find(song)             # official-channel list on disk: no quota used
        if indexed:
            db().execute("INSERT OR REPLACE INTO yt_cache_v4 (song_key, video_id) VALUES (?, ?)", (key, ",".join(indexed)))
            db().commit()
            return done(indexed)
        if not app.config["YOUTUBE_API_KEY"]:
            out["reason"] = "no_key"
            return jsonify(out)
        if time.time() < quota["until"]:
            out["reason"] = "quota"
            return jsonify(out)
        if key in no_result:
            out["reason"] = "not_found"
            return jsonify(out)
        head = (library.lyrics(song_id) or {}).get("tamil", "")[:700]
        ids, reason = youtube.search_song(app.config["YOUTUBE_API_KEY"], {**song, "tamil_head": head},
                                         region=app.config["YOUTUBE_REGION"])
        if ids:
            db().execute("INSERT OR REPLACE INTO yt_cache_v4 (song_key, video_id) VALUES (?, ?)",
                         (key, ",".join(ids)))
            db().commit()
            return done(ids)
        if reason:
            if reason == "quota":
                quota["until"] = time.time() + 3600
            out["reason"] = reason
        else:
            no_result.add(key)
            out["reason"] = "not_found"
        return jsonify(out)

    @app.get("/api/playable")
    @login_required
    def api_playable(user):
        """Which of these songs can play right now without a YouTube search (used to skip over the rest)."""
        try:
            ids = [int(x) for x in request.args.get("ids", "").split(",") if x][:40]
        except ValueError:
            return err("Bad id list.")
        return jsonify(playable=[i for i in ids if library.get(i) and has_video(library.get(i))])

    @app.post("/api/play/<int:song_id>/broken")
    @login_required
    def api_play_broken(user, song_id):
        """The page reports videos that would not play, so they are forgotten and the song is searched again next time."""
        song = library.get(song_id)
        if not song:
            return err("Song not found.", 404)
        bad = set(youtube.clean_id_list((request.get_json(silent=True) or {}).get("ids") or []))
        key = youtube.song_key(song["title"], song["movie"])
        row = db().execute("SELECT video_id FROM yt_cache_v4 WHERE song_key = ?", (key,)).fetchone()
        if row and bad:
            left = [v for v in youtube.clean_id_list(row["video_id"].split(",")) if v not in bad]
            if left:
                db().execute("UPDATE yt_cache_v4 SET video_id = ? WHERE song_key = ?", (",".join(left), key))
            else:
                db().execute("DELETE FROM yt_cache_v4 WHERE song_key = ?", (key,))
            db().commit()
        return jsonify(ok=True)

    # ----------------------------------------------------- Mood Journey
    @app.post("/api/journey")
    @login_required
    def api_journey(user):
        """Builds the whole journey up-front: equal time stages from the start mood towards happy,
        each with its own songs. Nothing is analysed while the user listens."""
        data = request.get_json(silent=True) or {}
        minutes = data.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool):
            return err("Choose how long the journey should be.")
        try:
            plan = journey_plan(data.get("mood"), minutes)
        except ValueError as e:
            return err(str(e))
        favs = fav_ids_for(user["id"])
        years = age_years(current_age())
        used = set()
        stages = []
        for st in plan:
            need = max(3, min(12, -(-(st["end"] - st["start"]) // SONG_SLOT_SECONDS) + 1))
            pool = [s for s in library.pool(st["mood"], years=years) if s["id"] not in used]
            random.shuffle(pool)
            pool = prefer_playable(pool)
            picked = pool[:need]
            used.update(s["id"] for s in picked)
            stages.append({**st, "label": MOODS[st["mood"]]["label"], "color": MOODS[st["mood"]]["color"],
                           "emoji": MOODS[st["mood"]]["emoji"],
                           "songs": [song_json(s, favs) for s in picked]})
        return jsonify(stages=stages, total=minutes * 60, slot_seconds=SONG_SLOT_SECONDS,
                       youtube_enabled=youtube_enabled())

    # ===================================================== ADMIN PANEL
    # Completely separate from user login: its own session flag, own credentials (ADMIN_USERNAME / ADMIN_PASSWORD
    # in .env or the host's environment variables), CSRF protection and brute-force throttling.
    admin_hash = generate_password_hash(app.config["ADMIN_PASSWORD"]) if app.config["ADMIN_PASSWORD"] else None
    admin_fails = {}                       # ip -> [timestamps of failed logins]
    ADMIN_SESSION_SECONDS = 2 * 3600

    def admin_ok():
        return time.time() - session.get("admin_at", 0) < ADMIN_SESSION_SECONDS

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    def csrf_valid():
        sent = request.form.get("csrf", "")
        return bool(sent) and secrets.compare_digest(sent, session.get("csrf", ""))

    def admin_required(view):
        @wraps(view)
        def wrapper(*a, **kw):
            if not admin_ok():
                session.pop("admin_at", None)
                return redirect(url_for("admin_login"))
            return view(*a, **kw)
        return wrapper

    @app.after_request
    def admin_no_cache(resp):
        if request.path.startswith("/admin"):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if admin_ok():
            return redirect(url_for("admin_dashboard"))
        error = None
        if admin_hash is None:
            error = "Admin is not set up yet. Add ADMIN_PASSWORD to your environment (.env), then restart."
        elif request.method == "POST":
            ip = request.remote_addr or "?"
            now = time.time()
            recent = [t for t in admin_fails.get(ip, []) if now - t < 600]
            admin_fails[ip] = recent
            if not csrf_valid():
                error = "Session expired. Please try again."
            elif len(recent) >= 5:
                error = "Too many attempts. Wait 10 minutes and try again."
            else:
                user_ok = secrets.compare_digest(request.form.get("username", "").strip().encode(),
                                                 app.config["ADMIN_USERNAME"].encode())
                pass_ok = check_password_hash(admin_hash, request.form.get("password", ""))
                if user_ok and pass_ok:
                    admin_fails.pop(ip, None)
                    session.clear()
                    session["admin_at"] = now
                    return redirect(url_for("admin_dashboard"))
                recent.append(now)
                error = "Wrong username or password."
        return render_template("admin_login.html", error=error), (429 if error and "Too many" in error else 200)

    @app.post("/admin/logout")
    def admin_logout():
        if csrf_valid():
            session.pop("admin_at", None)
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    @admin_required
    def admin_dashboard():
        q = db().execute
        one = lambda sql, *a: q(sql, a).fetchone()[0]
        totals = {
            "users": one("SELECT COUNT(*) FROM users"),
            "new_week": one("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now','-7 days')"),
            "moods": one("SELECT COUNT(*) FROM mood_history"),
            "favs": one("SELECT COUNT(*) FROM favorites"),
            "songs": len(library.songs),
        }
        mood_counts = {m: 0 for m in MOOD_ORDER}
        for r in q("SELECT mood, COUNT(*) c FROM mood_history GROUP BY mood"):
            if r["mood"] in mood_counts:
                mood_counts[r["mood"]] = r["c"]
        sources = {r["source"]: r["c"] for r in q("SELECT source, COUNT(*) c FROM mood_history GROUP BY source")}
        per_day = {r["d"]: r["c"] for r in q(
            "SELECT date(created_at) d, COUNT(*) c FROM mood_history "
            "WHERE created_at >= date('now','-6 days') GROUP BY d")}
        today = time.time()
        days = []
        for i in range(6, -1, -1):
            d = time.strftime("%Y-%m-%d", time.gmtime(today - i * 86400))
            days.append({"label": time.strftime("%a", time.gmtime(today - i * 86400)), "n": per_day.get(d, 0)})
        recent_users = q("SELECT id, name, email, avatar, created_at FROM users ORDER BY id DESC LIMIT 6").fetchall()
        activity = q("SELECT h.mood, h.source, h.created_at, u.name FROM mood_history h "
                     "JOIN users u ON u.id = h.user_id ORDER BY h.id DESC LIMIT 8").fetchall()
        return render_template("admin_dashboard.html", totals=totals, mood_counts=mood_counts, sources=sources,
                               days=days, recent_users=recent_users, activity=activity,
                               youtube_on=youtube_enabled(), google_on=bool(app.config["GOOGLE_CLIENT_ID"]),
                               mood_order=MOOD_ORDER)

    @app.get("/admin/users")
    @admin_required
    def admin_users():
        term = request.args.get("q", "").strip()[:60]
        like = f"%{term}%"
        rows = db().execute(
            "SELECT u.id, u.name, u.email, u.avatar, u.google_sub, u.created_at, "
            "(SELECT COUNT(*) FROM mood_history WHERE user_id = u.id) moods, "
            "(SELECT COUNT(*) FROM favorites WHERE user_id = u.id) favs "
            "FROM users u WHERE (? = '' OR u.name LIKE ? OR u.email LIKE ?) ORDER BY u.id DESC LIMIT 300",
            (term, like, like)).fetchall()
        return render_template("admin_users.html", rows=rows, term=term)

    @app.post("/admin/users/<int:user_id>/delete")
    @admin_required
    def admin_delete_user(user_id):
        if csrf_valid():
            db().execute("DELETE FROM users WHERE id = ?", (user_id,))     # history + favorites go too (ON DELETE CASCADE)
            db().commit()
        return redirect(url_for("admin_users"))

    return app


if __name__ == "__main__":
    application = create_app()
    prod = os.environ.get("APP_ENV", "").lower() == "production"
    application.run(host="0.0.0.0" if prod else "127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=not prod)
