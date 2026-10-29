import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from moods import (JOURNEY_MINUTES, JOURNEY_PATHS, MOODS, QUIZ, VALENCE_ENERGY,  # noqa: E402
                   journey_plan, mood_from_quiz)

TAMIL = re.compile("[஀-௿]")


@pytest.fixture()
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "GOOGLE_CLIENT_ID": "",
        "YOUTUBE_API_KEY": "",
        "YOUTUBE_IDS_FILE": str(tmp_path / "ids.csv"),            # never read the real id files in tests
        "CURATED_SEED_FILE": str(tmp_path / "seed.csv"),
    })


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def logged_in_noage(client):
    r = client.post("/api/signup", json={"name": "Muthu Mari", "email": "muthu@example.com", "password": "secret1"})
    assert r.status_code == 201
    return client


@pytest.fixture()
def logged_in(logged_in_noage):
    """Logged in AND an age group already chosen on the Detect page (most tests need that)."""
    assert logged_in_noage.post("/api/age", json={"age": "young"}).status_code == 200
    return logged_in_noage


# ---------------------------------------------------------------- pages
def test_splash_page_and_target(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Memodify" in r.data
    assert b'data-next="/login"' in r.data


def test_login_page_has_signup_and_google(client):
    r = client.get("/login")
    assert r.status_code == 200 and b"Sign up" in r.data and b"Continue with Google" in r.data


PAGES = ["/home", "/detect", "/face", "/quiz", "/emoji", "/history", "/favorites", "/journey", "/results?mood=happy"]


@pytest.mark.parametrize("path", PAGES)
def test_protected_pages_redirect(client, path):
    r = client.get(path)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


@pytest.mark.parametrize("path", PAGES + ["/journey?mood=angry", "/journey?mood=bogus"])
def test_pages_render_when_logged_in(logged_in, path):
    assert logged_in.get(path).status_code == 200


def test_splash_goes_home_when_logged_in(logged_in):
    assert b'data-next="/home"' in logged_in.get("/").data


def test_results_bad_mood_redirects_home(logged_in):
    assert logged_in.get("/results?mood=nonsense").status_code == 302


def test_static_assets_exist(client):
    for p in ["/static/css/style.css", "/static/img/logo.png", "/static/js/face.js", "/static/js/journey.js",
              "/static/js/chart.js", "/static/vendor/face-api/face-api.js",
              "/static/vendor/face-api/model/tiny_face_detector_model-weights_manifest.json",
              "/static/vendor/face-api/model/face_expression_model.bin",
              "/static/vendor/face-api/model/tiny_face_detector_model.bin"]:
        r = client.get(p)
        assert r.status_code == 200, p
        r.close()


def test_ui_is_english_except_quiz(logged_in):
    """Tamil must appear only in the quiz (questions + answers)."""
    for path in ["/home", "/detect", "/face", "/emoji", "/history", "/favorites", "/journey", "/results?mood=sad", "/quiz"]:
        html = logged_in.get(path).get_data(as_text=True)
        assert not TAMIL.search(html), path
    for api in ["/api/emojis", "/api/journey"]:
        pass
    assert not TAMIL.search(logged_in.get("/api/emojis").get_data(as_text=True).encode().decode("unicode_escape", "ignore"))
    q = logged_in.get("/api/quiz").get_json()["questions"]
    assert all(TAMIL.search(x["ta"]) and x["en"] for x in q)


def test_no_download_links_anywhere(logged_in):
    for path in ["/home", "/journey", "/results?mood=sad", "/favorites"]:
        html = logged_in.get(path).get_data(as_text=True).lower()
        assert "download" not in html and "<audio" not in html, path
    for js in ["songs.js", "journey.js", "player.js"]:
        src = (ROOT / "static" / "js" / js).read_text(encoding="utf-8").lower()
        assert ".download" not in src and "createobjecturl" not in src


# ----------------------------------------------------------------- auth
def test_signup_validation(client):
    assert client.post("/api/signup", json={"name": "A", "email": "a@b.co", "password": "123456"}).status_code == 400
    assert client.post("/api/signup", json={"name": "Abi", "email": "bad", "password": "123456"}).status_code == 400
    assert client.post("/api/signup", json={"name": "Abi", "email": "a@b.co", "password": "123"}).status_code == 400
    assert client.post("/api/signup", data="not json").status_code == 400


def test_signup_duplicate_login_logout(client):
    body = {"name": "Abi", "email": "Abi@Example.com", "password": "abcdef"}
    assert client.post("/api/signup", json=body).status_code == 201
    client.get("/logout")
    assert client.get("/home").status_code == 302
    assert client.post("/api/signup", json=body).status_code == 409
    assert client.post("/api/login", json={"email": "abi@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"email": "nobody@example.com", "password": "abcdef"}).status_code == 401
    ok = client.post("/api/login", json={"email": "abi@example.com", "password": "abcdef"})
    assert ok.status_code == 200 and ok.get_json()["redirect"] == "/home"
    assert client.get("/home").status_code == 200


def test_password_is_hashed(app, logged_in):
    row = sqlite3.connect(app.config["DATABASE"]).execute("SELECT password_hash FROM users").fetchone()
    assert row[0] and "secret1" not in row[0]


def test_api_requires_login(client):
    for method, url in [("get", "/api/quiz"), ("get", "/api/songs?mood=happy"), ("get", "/api/lyrics/1"),
                        ("get", "/api/play/1")]:
        assert getattr(client, method)(url).status_code == 401, url
    assert client.post("/api/recommend", json={"source": "emoji", "emoji": "😄"}).status_code == 401
    assert client.post("/api/journey", json={"mood": "sad", "minutes": 20}).status_code == 401


def test_google_not_configured(client):
    assert client.post("/api/google", json={"credential": "x"}).status_code == 503


def test_google_login_flow(app, client):
    app.config["GOOGLE_CLIENT_ID"] = "test-client-id"

    def fake_verify(token):
        if token == "good":
            return {"email": "g@example.com", "email_verified": True, "sub": "123", "name": "G User", "picture": "http://x/y.png"}
        if token == "unverified":
            return {"email": "u@example.com", "email_verified": False, "sub": "9"}
        raise ValueError("bad token")

    app.verify_google_token = fake_verify
    assert client.post("/api/google", json={}).status_code == 400
    assert client.post("/api/google", json={"credential": "bad"}).status_code == 401
    assert client.post("/api/google", json={"credential": "unverified"}).status_code == 401
    assert client.post("/api/google", json={"credential": "good"}).status_code == 200
    assert client.get("/home").status_code == 200
    client.get("/logout")
    assert client.post("/api/google", json={"credential": "good"}).status_code == 200
    assert sqlite3.connect(app.config["DATABASE"]).execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_real_google_verifier_rejects_garbage(app):
    app.config["GOOGLE_CLIENT_ID"] = "test-client-id"
    with pytest.raises(Exception):
        app.verify_google_token("not-a-real-token")


# ----------------------------------------------------------- mood logic
def test_quiz_endpoint_hides_scores(logged_in):
    qs = logged_in.get("/api/quiz").get_json()["questions"]
    assert len(qs) == 5
    for q in qs:
        assert q["ta"] and q["en"] and len(q["options"]) >= 2
        for o in q["options"]:
            assert "score" not in o and o["ta"] and o["en"]


def test_quiz_scoring_each_mood():
    for mood in MOODS:
        answers = [max(range(len(q["options"])), key=lambda i: q["options"][i]["score"].get(mood, 0)) for q in QUIZ]
        got, scores = mood_from_quiz(answers)
        assert got == mood, (mood, scores)


@pytest.mark.parametrize("bad", [None, [], [0, 0, 0, 0], [0, 0, 0, 0, 9], [0, 0, 0, 0, -1], [0, 0, 0, 0, "1"], [True] * 5])
def test_quiz_rejects_bad_answers(logged_in, bad):
    assert logged_in.post("/api/recommend", json={"source": "quiz", "answers": bad}).status_code == 400


def test_quiz_recommend_ok(logged_in):
    r = logged_in.post("/api/recommend", json={"source": "quiz", "answers": [0, 3, 2, 0, 0]})
    j = r.get_json()
    assert r.status_code == 200 and j["mood"] in MOODS and j["redirect"].startswith("/results?mood=")


def test_emoji_all_map_to_valid_mood(logged_in):
    emojis = logged_in.get("/api/emojis").get_json()["emojis"]
    assert len(emojis) == 7 and all(e["label"] for e in emojis)
    for e in emojis:
        r = logged_in.post("/api/recommend", json={"source": "emoji", "emoji": e["emoji"]})
        assert r.status_code == 200 and r.get_json()["mood"] in MOODS
    assert logged_in.post("/api/recommend", json={"source": "emoji", "emoji": "🐶"}).status_code == 400


@pytest.mark.parametrize("emotion,mood", [
    ("happy", "happy"), ("sad", "sad"), ("angry", "angry"), ("surprised", "energetic"),
    ("neutral", "calm"), ("fearful", "calm"), ("disgusted", "angry")])
def test_face_mapping(logged_in, emotion, mood):
    expr = {k: 0.02 for k in ["neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised"]}
    expr[emotion] = 0.9
    r = logged_in.post("/api/recommend", json={"source": "face", "expressions": expr})
    j = r.get_json()
    assert r.status_code == 200 and j["mood"] == mood and j["emotion"] == emotion


@pytest.mark.parametrize("bad", [None, {}, {"happy": "high"}, {"happy": 5}, {"alien": 0.9}, [1, 2]])
def test_face_rejects_bad_payload(logged_in, bad):
    assert logged_in.post("/api/recommend", json={"source": "face", "expressions": bad}).status_code == 400


def test_unknown_source(logged_in):
    assert logged_in.post("/api/recommend", json={"source": "magic"}).status_code == 400


# ------------------------------------------------------------- songs
@pytest.mark.parametrize("mood", list(MOODS))
def test_songs_for_every_mood(logged_in, mood):
    j = logged_in.get(f"/api/songs?mood={mood}").get_json()
    assert len(j["songs"]) == 8
    ids = [s["id"] for s in j["songs"]]
    assert len(ids) == len(set(ids))
    for s in j["songs"]:
        assert s["mood"] == mood and s["title"] and 0 <= s["valence"] <= 1
        assert s["search_url"].startswith("https://www.youtube.com/results") and "tamil" in s["search_url"].lower()
        assert "video_id" not in s and "youtube_id" not in s     # YouTube is an optional extra, never the main source


def test_songs_bad_mood_and_exclude(app, logged_in):
    assert logged_in.get("/api/songs?mood=zzz").status_code == 400
    assert logged_in.get("/api/songs?mood=happy&exclude=a,b").status_code == 400
    first_ids = {s["id"] for s in logged_in.get("/api/songs?mood=happy").get_json()["songs"]}
    second = logged_in.get("/api/songs?mood=happy&exclude=" + ",".join(map(str, first_ids))).get_json()["songs"]
    assert {s["id"] for s in second}.isdisjoint(first_ids) and len(second) == 8


def test_lyrics_endpoint(logged_in):
    songs = logged_in.get("/api/songs?mood=calm").get_json()["songs"]
    sid = next(x["id"] for x in songs if x["has_lyrics"])
    j = logged_in.get(f"/api/lyrics/{sid}").get_json()
    assert TAMIL.search(j["tamil"]) and len(j["tamil"]) > 100 and j["english"]
    assert logged_in.get("/api/lyrics/9999999").status_code == 404


def test_favorites_toggle_and_page(logged_in):
    sid = logged_in.get("/api/songs?mood=calm").get_json()["songs"][0]["id"]
    assert logged_in.post(f"/api/favorites/{sid}").get_json()["favorite"] is True
    page = logged_in.get("/favorites").get_data(as_text=True)
    data = json.loads(re.search(r'<script id="songs-data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert [s["id"] for s in data] == [sid] and data[0]["favorite"] is True
    assert logged_in.post(f"/api/favorites/{sid}").get_json()["favorite"] is False
    assert 'id="songs-data"' not in logged_in.get("/favorites").get_data(as_text=True)
    assert logged_in.post("/api/favorites/99999999").status_code == 404


def test_favorites_are_per_user(app, logged_in):
    sid = logged_in.get("/api/songs?mood=calm").get_json()["songs"][0]["id"]
    logged_in.post(f"/api/favorites/{sid}")
    other = app.test_client()
    other.post("/api/signup", json={"name": "Other", "email": "o@example.com", "password": "abcdef"})
    assert b'id="songs-data"' not in other.get("/favorites").data


def test_history_saved_and_shown(logged_in):
    logged_in.post("/api/recommend", json={"source": "emoji", "emoji": "😢"})
    page = logged_in.get("/history").get_data(as_text=True)
    assert "Sad" in page
    assert "Hello, Muthu!" in logged_in.get("/home").get_data(as_text=True)


# --------------------------------------------- optional YouTube playback
def test_play_without_key_is_optional(logged_in):
    j = logged_in.get("/api/play/1").get_json()
    assert j["enabled"] is False and j["video_id"] == "" and "youtube.com/results" in j["search_url"]
    assert logged_in.get("/api/play/99999999").status_code == 404


def test_play_with_key_uses_cache(app, logged_in, monkeypatch):
    import youtube as _yt
    monkeypatch.setattr(_yt, "is_right_song", lambda item, song: True)     # matching itself is tested separately
    import io
    import urllib.request
    app.config["YOUTUBE_API_KEY"] = "fake"
    calls = []

    def fake_urlopen(url, timeout=0):
        calls.append(url)
        return io.BytesIO(json.dumps({"items": [{"id": {"videoId": "abc123XYZ_-"}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    a = logged_in.get("/api/play/5").get_json()
    b = logged_in.get("/api/play/5").get_json()
    assert a["video_id"] == b["video_id"] == "abc123XYZ_-" and a["enabled"] is True
    searches = [c for c in calls if "/search?" in c]
    assert len(searches) == 1 and "videoEmbeddable=true" in searches[0]    # second answer came from the cache (saves API quota)


def test_play_with_key_survives_api_failure(app, logged_in, monkeypatch):
    import urllib.request
    app.config["YOUTUBE_API_KEY"] = "fake"

    def boom(url, timeout=0):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    j = logged_in.get("/api/play/5").get_json()
    assert j["video_id"] == "" and j["enabled"] is True


# --------------------------------------------- in-page playback (new)
def _song(app, i=5):
    return app.library.get(i)


def test_known_ids_file_plays_without_api_key(app, logged_in):
    s = _song(app)
    Path(app.config["YOUTUBE_IDS_FILE"]).write_text(
        f"title,movie,video_id\n{s['title']},{s['movie']},https://www.youtube.com/watch?v=abc123XYZ_-\n"
        f"{s['title']},{s['movie']},zzzzzzzzzzz\n", encoding="utf-8")
    j = logged_in.get("/api/play/5").get_json()
    assert j["candidates"] == ["abc123XYZ_-", "zzzzzzzzzzz"] and j["video_id"] == "abc123XYZ_-"
    assert j["enabled"] is True                                  # ids exist, so in-page playback is on
    assert logged_in.get("/api/config").get_json()["youtube_enabled"] is True


def test_known_ids_file_edits_are_picked_up_without_restart(app, logged_in):
    f = Path(app.config["YOUTUBE_IDS_FILE"])
    assert logged_in.get("/api/play/5").get_json()["candidates"] == []
    s = _song(app)
    f.write_text(f"title,movie,video_id\n{s['title']},{s['movie']},abc123XYZ_-\n", encoding="utf-8")
    assert logged_in.get("/api/play/5").get_json()["candidates"] == ["abc123XYZ_-"]


def test_bad_ids_are_ignored(app, logged_in):
    s = _song(app)
    Path(app.config["YOUTUBE_IDS_FILE"]).write_text(
        f"title,movie,video_id\n{s['title']},{s['movie']},not-an-id\n", encoding="utf-8")
    assert logged_in.get("/api/play/5").get_json()["candidates"] == []


def test_play_returns_several_candidates_and_reason(app, logged_in, monkeypatch):
    import youtube as _yt
    monkeypatch.setattr(_yt, "is_right_song", lambda item, song: True)     # matching itself is tested separately
    import io
    import urllib.request
    app.config["YOUTUBE_API_KEY"] = "fake"
    items = [{"id": {"videoId": v}} for v in ("aaaaaaaaaaa", "bbbbbbbbbbb", "bad id!", "ccccccccccc")]
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=0: io.BytesIO(json.dumps({"items": items}).encode()))
    j = logged_in.get("/api/play/7").get_json()
    assert j["candidates"] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"] and j["reason"] == ""
    # the cache keeps all candidates for the next visit
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert logged_in.get("/api/play/7").get_json()["candidates"] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]


def test_play_reasons(app, logged_in, monkeypatch):
    import io
    import urllib.error
    import urllib.request
    assert logged_in.get("/api/play/5").get_json()["reason"] == "no_key"
    app.config["YOUTUBE_API_KEY"] = "fake"

    def quota(url, timeout=0):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'))

    monkeypatch.setattr(urllib.request, "urlopen", quota)
    assert logged_in.get("/api/play/5").get_json()["reason"] == "quota"
    app.quota["until"] = 0                    # (the app pauses searches for an hour after a quota error)

    def badkey(url, timeout=0):
        raise urllib.error.HTTPError(url, 400, "Bad", {}, io.BytesIO(b'{"error":{"message":"API key not valid","errors":[{"reason":"keyInvalid"}]}}'))

    monkeypatch.setattr(urllib.request, "urlopen", badkey)
    assert logged_in.get("/api/play/6").get_json()["reason"] == "key"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert logged_in.get("/api/play/8").get_json()["reason"] == "error"


def test_not_found_is_not_searched_again(app, logged_in, monkeypatch):
    import youtube as _yt
    monkeypatch.setattr(_yt, "is_right_song", lambda item, song: True)     # matching itself is tested separately
    import io
    import urllib.request
    app.config["YOUTUBE_API_KEY"] = "fake"
    calls = []

    def empty(url, timeout=0):
        calls.append(url)
        return io.BytesIO(b'{"items": []}')

    monkeypatch.setattr(urllib.request, "urlopen", empty)
    assert logged_in.get("/api/play/9").get_json()["reason"] == "not_found"
    assert logged_in.get("/api/play/9").get_json()["reason"] == "not_found"
    assert len(calls) == 1


def test_play_requires_login(client):
    assert client.get("/api/play/1").status_code == 401


def test_results_and_favorites_have_player(logged_in):
    for path in ["/results?mood=happy"]:
        html = logged_in.get(path).get_data(as_text=True)
        assert 'id="player-slot"' in html and "js/player.js" in html
    logged_in.post("/api/favorites/1")
    html = logged_in.get("/favorites").get_data(as_text=True)
    assert 'id="player-slot"' in html and "js/player.js" in html


def test_song_rows_do_not_send_people_to_youtube():
    src = (ROOT / "static" / "js" / "songs.js").read_text(encoding="utf-8")
    assert "search_url" not in src and "youtube.com" not in src and "target = '_blank'" not in src
    assert "Player.play" in src


def test_fetch_tool_saves_ids_and_resumes(tmp_path, monkeypatch):
    import youtube as _yt
    monkeypatch.setattr(_yt, "is_right_song", lambda item, song: True)     # matching itself is tested separately
    import io
    import urllib.request
    sys.path.insert(0, str(ROOT / "tools"))
    import fetch_youtube_ids as tool
    out = tmp_path / "ids.csv"
    n = {"i": 0}

    def fake(url, timeout=0):
        n["i"] += 1
        return io.BytesIO(json.dumps({"items": [{"id": {"videoId": f"vid{n['i']:08d}"}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert tool.main(["--key", "k", "--out", str(out), "--limit", "4", "--per-mood", "2"]) == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert len(rows) == 4 and all(len(r["video_id"]) == 11 for r in rows)
    assert tool.main(["--key", "k", "--out", str(out), "--limit", "4", "--per-mood", "2"]) == 0
    rows2 = list(csv.DictReader(open(out, encoding="utf-8")))
    assert len(rows2) == 8 and len({(r["title"], r["movie"]) for r in rows2}) == 8      # resumed: no song repeated
    assert tool.main(["--out", str(out), "--limit", "1", "--key", ""]) == 2               # no key -> clear exit code


def test_shipped_id_files_hold_only_valid_ids():
    for name in ("youtube_ids.csv", "curated_seed.csv"):
        for r in csv.DictReader(open(ROOT / "data" / name, encoding="utf-8-sig")):
            vid = (r.get("video_id") or r.get("youtube_id") or "").strip()
            assert not vid or re.fullmatch(r"[A-Za-z0-9_-]{11}", vid), (name, r)


# ------------------------------------------- flow: Home -> Detect Mood -> Face / Quiz / Emoji
def test_home_has_detect_button_but_not_the_three_methods(logged_in):
    html = logged_in.get("/home").get_data(as_text=True)
    assert 'href="/detect"' in html and "Detect Mood" in html
    for p in ("/face", "/quiz", "/emoji"):
        assert f'href="{p}"' not in html


def test_detect_page_offers_exactly_the_three_methods(logged_in):
    html = logged_in.get("/detect").get_data(as_text=True)
    for p in ("/face", "/quiz", "/emoji"):
        assert html.count(f'href="{p}"') == 1


@pytest.mark.parametrize("path", ["/home", "/results?mood=happy", "/favorites", "/history", "/journey", "/face", "/quiz", "/emoji"])
def test_three_methods_are_listed_only_on_the_detect_page(logged_in, path):
    html = logged_in.get(path).get_data(as_text=True)
    assert sum(f'href="{p}"' in html for p in ("/face", "/quiz", "/emoji")) == 0, path


# ------------------------------------------- official songs first, unplayable videos dropped
def test_official_videos_rank_above_covers_and_remixes():
    import youtube
    song = {"title": "Kaattu Sirukki", "movie": "Raavanan"}

    def it(vid, title, chan):
        return {"id": {"videoId": vid}, "snippet": {"title": title, "channelTitle": chan}}

    items = [it("cover000001", "Kaattu Sirukki cover by me", "Random Guy"),
             it("remix000001", "Kaattu Sirukki remix DJ", "DJ X"),
             it("lyric000001", "Kaattu Sirukki Lyric Video | Raavanan", "Some Fan"),
             it("offic000001", "Kaattu Sirukki Official Video Song | Raavanan | A.R. Rahman", "Sony Music South")]
    best = sorted(items, key=lambda i: -youtube.score(i, song))
    assert best[0]["id"]["videoId"] == "offic000001" and best[1]["id"]["videoId"] == "lyric000001"
    assert {best[-1]["id"]["videoId"], best[-2]["id"]["videoId"]} == {"cover000001", "remix000001"}


def test_search_drops_blocked_and_non_embeddable_videos(monkeypatch):
    import io
    import youtube
    import urllib.request

    def fake(url, timeout=0):
        if "/search?" in url:
            assert "regionCode=IN" in url
            return io.BytesIO(json.dumps({"items": [{"id": {"videoId": v}} for v in
                                                   ("good0000001", "blocked0001", "noembed0001", "private0001", "gone0000001")]}).encode())
        return io.BytesIO(json.dumps({"items": [
            {"id": "good0000001", "status": {"embeddable": True, "privacyStatus": "public"}, "contentDetails": {}},
            {"id": "blocked0001", "status": {"embeddable": True, "privacyStatus": "public"}, "contentDetails": {"regionRestriction": {"blocked": ["IN"]}}},
            {"id": "noembed0001", "status": {"embeddable": False, "privacyStatus": "public"}, "contentDetails": {}},
            {"id": "private0001", "status": {"embeddable": True, "privacyStatus": "private"}, "contentDetails": {}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ids, reason = youtube.search("k", "x")
    assert ids == ["good0000001"] and reason == ""


def test_broken_report_forgets_videos(app, logged_in, monkeypatch):
    import youtube as _yt
    monkeypatch.setattr(_yt, "is_right_song", lambda item, song: True)     # matching itself is tested separately
    import io
    import urllib.request
    app.config["YOUTUBE_API_KEY"] = "fake"
    items = [{"id": {"videoId": v}} for v in ("aaaaaaaaaaa", "bbbbbbbbbbb")]
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0: io.BytesIO(json.dumps({"items": items}).encode()))
    assert logged_in.get("/api/play/5").get_json()["candidates"] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert logged_in.post("/api/play/5/broken", json={"ids": ["aaaaaaaaaaa"]}).status_code == 200
    assert logged_in.get("/api/play/5").get_json()["candidates"] == ["bbbbbbbbbbb"]
    logged_in.post("/api/play/5/broken", json={"ids": ["bbbbbbbbbbb"]})
    items[:] = [{"id": {"videoId": "ccccccccccc"}}]                 # next lookup asks YouTube again
    assert logged_in.get("/api/play/5").get_json()["candidates"] == ["ccccccccccc"]
    assert logged_in.post("/api/play/5/broken", json={"ids": ["x"]}).status_code == 200
    assert logged_in.post("/api/play/99999999/broken", json={}).status_code == 404


# ------------------------------------------- age groups: songs from the years people grew up with
def test_age_must_be_chosen_before_the_methods(logged_in_noage):
    for p in ("/face", "/quiz", "/emoji"):
        r = logged_in_noage.get(p)
        assert r.status_code == 302 and r.headers["Location"].endswith("/detect")
    r = logged_in_noage.post("/api/recommend", json={"source": "emoji", "emoji": "😄"})
    assert r.status_code == 400 and "age" in r.get_json()["error"].lower()
    assert logged_in_noage.post("/api/age", json={"age": "martian"}).status_code == 400
    assert logged_in_noage.post("/api/age", json={}).status_code == 400
    assert logged_in_noage.post("/api/age", json={"age": "adult"}).status_code == 200
    assert logged_in_noage.get("/face").status_code == 200


def test_detect_page_lists_all_age_groups(logged_in_noage):
    import moods
    html = logged_in_noage.get("/detect").get_data(as_text=True)
    for k, g in moods.AGE_GROUPS.items():
        assert f'data-age="{k}"' in html and g["label"] in html
    assert "locked" in html                                     # methods stay locked until an age is chosen
    logged_in_noage.post("/api/age", json={"age": "mid"})
    html = logged_in_noage.get("/detect").get_data(as_text=True)
    assert "locked" not in html and 'class="age selected"' in html


@pytest.mark.parametrize("age", ["teen", "young", "adult", "mid", "senior", "elder"])
@pytest.mark.parametrize("mood", ["happy", "sad", "calm", "energetic", "romantic", "angry"])
def test_every_mood_and_age_gives_songs_from_that_era(app, logged_in_noage, age, mood):
    import moods
    logged_in_noage.post("/api/age", json={"age": age})
    lo, hi = moods.AGE_GROUPS[age]["years"]
    songs = logged_in_noage.get(f"/api/songs?mood={mood}").get_json()["songs"]
    assert len(songs) == 8 and all(s["mood"] == mood for s in songs)
    years = [s["year"] for s in songs if s["year"]]
    assert years and all(lo - 15 <= y <= hi + 15 for y in years)           # widening is limited to 15 years
    inside = sum(lo <= y <= hi for y in years)
    assert inside >= len(years) * 0.7                                      # and most songs are inside the era


def test_recommend_redirect_and_results_carry_the_age(logged_in_noage):
    logged_in_noage.post("/api/age", json={"age": "senior"})
    r = logged_in_noage.post("/api/recommend", json={"source": "emoji", "emoji": "😄"}).get_json()
    assert "age=senior" in r["redirect"]
    html = logged_in_noage.get(r["redirect"]).get_data(as_text=True)
    assert "Age 51 - 65" in html and "1978-1995" in html and 'data-age="senior"' in html
    assert logged_in_noage.get("/results?mood=happy&age=nonsense").status_code == 200   # bad value is ignored


def test_old_songs_for_elders_and_new_songs_for_teens(logged_in_noage):
    logged_in_noage.post("/api/age", json={"age": "elder"})
    old = [s["year"] for s in logged_in_noage.get("/api/songs?mood=romantic").get_json()["songs"]]
    logged_in_noage.post("/api/age", json={"age": "teen"})
    new = [s["year"] for s in logged_in_noage.get("/api/songs?mood=romantic").get_json()["songs"]]
    assert max(old) <= 1995 and min(new) >= 2010 and sum(old) / 8 < sum(new) / 8 - 25


def test_journey_uses_the_age_group(logged_in_noage):
    import moods
    logged_in_noage.post("/api/age", json={"age": "mid"})
    j = logged_in_noage.post("/api/journey", json={"mood": "sad", "minutes": 20}).get_json()
    years = [s["year"] for st in j["stages"] for s in st["songs"] if s["year"]]
    lo, hi = moods.AGE_GROUPS["mid"]["years"]
    assert years and sum(lo <= y <= hi for y in years) >= len(years) * 0.8
    assert "Songs for age 36 - 50" in logged_in_noage.get("/journey").get_data(as_text=True)


# --------------------------------------------------------- Mood Journey
@pytest.mark.parametrize("start", list(JOURNEY_PATHS))
@pytest.mark.parametrize("minutes", JOURNEY_MINUTES)
def test_journey_plan_shape(start, minutes):
    plan = journey_plan(start, minutes)
    assert [s["mood"] for s in plan] == JOURNEY_PATHS[start]
    assert plan[0]["start"] == 0 and plan[-1]["end"] == minutes * 60
    assert all(a["end"] == b["start"] for a, b in zip(plan, plan[1:]))
    assert all(s["end"] > s["start"] for s in plan)
    from moods import SONG_SLOT_SECONDS
    assert all(s["end"] - s["start"] >= SONG_SLOT_SECONDS for s in plan)     # every stage has room for a whole song


@pytest.mark.parametrize("start", list(JOURNEY_PATHS))
def test_journey_moves_towards_happy(start):
    val = [VALENCE_ENERGY[m][0] for m in JOURNEY_PATHS[start]]
    if start in ("happy", "energetic"):
        assert min(val) >= 0.7                      # already positive: the journey just keeps the good mood going
    else:
        assert all(b >= a - 1e-9 for a, b in zip(val, val[1:])), (start, val)   # never gets worse on the way
        assert JOURNEY_PATHS[start][-1] == "happy" and val[-1] > val[0]


@pytest.mark.parametrize("bad", [
    {"mood": "sad", "minutes": 7}, {"mood": "nope", "minutes": 20}, {"mood": "sad"},
    {"mood": "sad", "minutes": "20"}, {"mood": "sad", "minutes": True}, {"minutes": 20}, {}])
def test_journey_rejects_bad_input(logged_in, bad):
    assert logged_in.post("/api/journey", json=bad).status_code == 400


def test_journey_api_builds_whole_route(logged_in):
    j = logged_in.post("/api/journey", json={"mood": "sad", "minutes": 30}).get_json()
    assert j["total"] == 1800 and [s["mood"] for s in j["stages"]] == ["sad", "calm", "romantic", "happy"]
    seen = set()
    for st in j["stages"]:
        assert 3 <= len(st["songs"]) <= 12 and st["label"] and st["color"].startswith("#")
        for s in st["songs"]:
            assert s["mood"] == st["mood"]
            assert s["id"] not in seen          # no song repeats inside one journey
            seen.add(s["id"])
        # enough songs to fill the stage even with the shortest song slot
        assert len(st["songs"]) * j["slot_seconds"] >= min(st["end"] - st["start"], 12 * j["slot_seconds"])
    assert j["youtube_enabled"] is False


def test_journey_page_has_controls(logged_in):
    html = logged_in.get("/journey?mood=angry").get_data(as_text=True)
    assert 'data-start="angry"' in html and "Begin journey" in html and 'id="chart"' in html
    assert all(f'data-minutes="{m}"' in html for m in JOURNEY_MINUTES)


# ------------------------------------------------------------ dataset
def test_dataset_files_present_and_consistent(app):
    lib = app.library
    assert len(lib.songs) > 4000
    for mood in MOODS:
        assert len(lib.by_mood[mood]) >= 300, mood
    keys = [(s["title"].lower(), s["movie"].lower()) for s in lib.songs]
    assert len(keys) == len(set(keys))
    assert all(s["title"] and s["title"][0].isalnum() for s in lib.songs)
    assert all(0 <= s["valence"] <= 1 and 0 <= s["energy"] <= 1 and 0 < s["confidence"] <= 1 for s in lib.songs)
    con = sqlite3.connect(ROOT / "data" / "lyrics.db")
    n = con.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0]
    assert n == len(lib.songs)
    ids = {r[0] for r in con.execute("SELECT id FROM lyrics")}
    assert ids == {s["id"] for s in lib.songs}


def test_dataset_all_songs_are_tamil(app):
    con = sqlite3.connect(ROOT / "data" / "lyrics.db")
    rows = con.execute("SELECT tamil FROM lyrics WHERE tamil != '' ORDER BY RANDOM() LIMIT 300").fetchall()
    assert sum(bool(TAMIL.search(r[0])) for r in rows) >= 295


def test_no_youtube_ids_are_invented(app):
    header = (ROOT / "data" / "songs.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "youtube" not in header.lower()          # the dataset has none, so we never fake them


def test_hand_labelled_songs_keep_their_mood(app):
    seed = {r["title"].lower(): r["mood"] for r in csv.DictReader(open(ROOT / "data" / "curated_seed.csv", encoding="utf-8"))}
    hits = [s for s in app.library.songs if s["title"].lower() in seed]
    assert hits, "expected some hand-labelled songs in the library"
    good = [s for s in hits if seed[s["title"].lower()] == s["mood"]]
    assert len(good) >= len(hits) * 0.8


def test_library_rejects_missing_columns(tmp_path):
    from recommender import SongLibrary
    bad = tmp_path / "bad.csv"
    bad.write_text("name,artist\nx,y\n")
    with pytest.raises(ValueError):
        SongLibrary(str(bad))


def test_every_script_a_page_loads_exists_and_is_not_empty():
    """Regression: results.js was once an empty file, so the Results page never loaded songs."""
    import re
    for tpl in (ROOT / "templates").glob("*.html"):
        for src in re.findall(r"filename='(js/[^']+)'", tpl.read_text(encoding="utf-8")):
            f = ROOT / "static" / src
            assert f.exists() and f.stat().st_size > 100, f"{tpl.name} loads {src} which is missing/empty"
    for f in (ROOT / "static" / "js").glob("*.js"):
        assert f.stat().st_size > 100, f"{f.name} is empty"


# ---------------------------------------------------------------- right song / right lyrics
def _item(title, chan="Think Music India", desc=""):
    return {"snippet": {"title": title, "channelTitle": chan, "description": desc}}


def test_video_must_be_the_same_song():
    import youtube
    song = {"title": "Yaarovai", "movie": "Angelina", "year": 2019,
            "tamil_head": "யாரோ வாய்\nவிழி முன்னே வந்தாய்"}
    assert youtube.is_right_song(_item("Yaarovai - Lyric Video | Angelina | D. Imman"), song)
    assert youtube.is_right_song(_item("Yaaro Vaai Video Song - Angelina"), song)       # spelling differs
    assert not youtube.is_right_song(_item("Oru Murai Piranthen Video Song", "Ayngaran"), song)
    assert not youtube.is_right_song(_item("ஒரு முறை பிறந்தேன் வீடியோ பாடல்", "Ayngaran"), song)   # Tamil-only title, other song
    assert not youtube.is_right_song(_item("Yaarovai Cover | Angelina"), song)             # covers are rejected
    assert not youtube.is_right_song(_item("Yaarovai", desc="a different film entirely"), {**song, "title": "Hey", "movie": "Other"})


def test_search_keeps_only_matching_videos(monkeypatch):
    import youtube
    items = [{"id": {"videoId": "AAAAAAAAAAA"}, **_item("Some Other Song Official Audio")},
             {"id": {"videoId": "BBBBBBBBBBB"}, **_item("Yaarovai Official Audio | Angelina")}]
    monkeypatch.setattr(youtube, "_call", lambda url, timeout: {"items": items})
    monkeypatch.setattr(youtube, "_playable", lambda key, ids, region, timeout: ids)
    ids, reason = youtube.search("k", "q", song={"title": "Yaarovai", "movie": "Angelina"})
    assert ids == ["BBBBBBBBBBB"] and reason == ""


def test_swapped_lyrics_are_fixed():
    """Four songs of one movie had each other's lyrics; each title must now appear in its own lyrics."""
    con = sqlite3.connect(ROOT / "data" / "lyrics.db")
    with open(ROOT / "data" / "songs.csv", encoding="utf-8-sig") as f:
        songs = {int(r["id"]): r for r in csv.DictReader(f)}
    sys.path.insert(0, str(ROOT / "tools"))
    from fix_data import fit
    for sid in (812, 2200, 3234, 4482):
        eng = con.execute("SELECT english FROM lyrics WHERE id = ?", (sid,)).fetchone()[0]
        assert fit(songs[sid]["title"], eng) >= 0.85, songs[sid]["title"]


def test_songs_without_lyrics_are_flagged(logged_in):
    lib = logged_in.application.library
    s = lib.get(5349)
    assert s and not lib.has_lyrics(5349) and lib.has_lyrics(5225)


def test_scenes_teasers_and_sneak_peeks_are_rejected():
    import youtube
    song = {"title": "Ivan Thanthiran", "movie": "Ivan Thanthiran", "year": 2017}
    for bad in ("Ivan Thanthiran - Sneak Peek | Gautham Karthik", "Ivan Thanthiran Climax Scene", "Ivan Thanthiran Official Teaser",
                "Ivan Thanthiran Trailer", "Ivan Thanthiran Making of the song", "Ivan Thanthiran Comedy Scenes",
                "Ivan Thanthiran Full Movie", "Ivan Thanthiran Promo", "Ivan Thanthiran | Fight Scene"):
        assert not youtube.is_right_song(_item(bad, "Murari Music Official"), song), bad
    assert youtube.is_right_song(_item("Ivan Thanthiran - Video Song | Gautham Karthik | S. Thaman"), song)
    assert youtube.is_right_song(_item("Ivan Thanthiran Lyric Video | Ivan Thanthiran", "Think Music India"), song)
    # a song that really is called "Climax" is not rejected for its own name
    assert youtube.is_right_song(_item("Climax - Official Video Song | Some Film"), {"title": "Climax", "movie": "Some Film"})


def test_duration_filter_drops_non_songs(monkeypatch):
    import youtube
    assert youtube._seconds("PT4M22S") == 262 and youtube._seconds("PT1H2M") == 3720 and youtube._seconds("") is None
    data = {"items": [{"id": "AAAAAAAAAAA", "status": {"embeddable": True}, "contentDetails": {"duration": "PT45S"}},
                      {"id": "BBBBBBBBBBB", "status": {"embeddable": True}, "contentDetails": {"duration": "PT4M10S"}},
                      {"id": "CCCCCCCCCCC", "status": {"embeddable": True}, "contentDetails": {"duration": "PT2H10M"}}]}
    monkeypatch.setattr(youtube, "_call", lambda url, timeout: data)
    assert youtube._playable("k", ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"], "IN", 5) == ["BBBBBBBBBBB"]


# ---------------------------------------------------------------- no-quota playing (local index)
def _write_index(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "title", "channel", "seconds"])
        w.writerows(rows)


def test_local_index_plays_without_any_key_or_search(app, logged_in, tmp_path):
    song = app.library.get(5225)                                       # Yaarovai - Angelina
    idx = tmp_path / "video_index.csv"
    _write_index(idx, [("AAAAAAAAAAA", "Yaarovai Lyric Video | Angelina | D. Imman", "Think Music India", 300),
                       ("BBBBBBBBBBB", "Yaarovai - Sneak Peek | Angelina", "Think Music India", 120),
                       ("CCCCCCCCCCC", "Totally Different Song | Other Film", "Think Music India", 250)])
    app.video_index.path = idx
    app.video_index._stamp = None
    j = logged_in.get("/api/play/5225").get_json()
    assert j["candidates"] == ["AAAAAAAAAAA"] and j["reason"] == ""    # sneak peek and other songs are not picked
    assert song["title"] == "Yaarovai"
    assert logged_in.get("/api/play/5225").get_json()["candidates"] == ["AAAAAAAAAAA"]     # now cached too


def test_quota_used_up_does_not_stop_the_app(app, logged_in, monkeypatch, tmp_path):
    import io
    import urllib.error
    import urllib.request
    app.config["YOUTUBE_API_KEY"] = "fake"
    idx = tmp_path / "video_index.csv"
    _write_index(idx, [("AAAAAAAAAAA", "Yaarovai Lyric Video | Angelina", "Think Music India", 300)])
    app.video_index.path = idx
    app.video_index._stamp = None
    calls = []

    def quota_error(url, timeout=0):
        calls.append(url)
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, io.BytesIO(b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}'))

    monkeypatch.setattr(urllib.request, "urlopen", quota_error)
    assert logged_in.get("/api/play/9").get_json()["reason"] == "quota"      # a song that needs a search
    assert len(calls) == 1
    assert logged_in.get("/api/play/10").get_json()["reason"] == "quota"     # does not hit YouTube again for a while
    assert len(calls) == 1
    assert logged_in.get("/api/play/5225").get_json()["candidates"] == ["AAAAAAAAAAA"]      # indexed song still plays
    r = logged_in.get("/api/playable?ids=9,10,5225").get_json()
    assert r["playable"] == [5225]
    songs = logged_in.get("/api/songs?mood=sad").get_json()["songs"]         # still a full list while the limit is out
    assert len(songs) == 8


def test_build_index_tool(tmp_path, monkeypatch):
    import io
    import urllib.request
    sys.path.insert(0, str(ROOT / "tools"))
    import build_video_index as tool

    def fake(url, timeout=0):
        if "/channels" in url:
            data = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUx"}}, "snippet": {"title": "Think Music India"}}]}
        elif "/playlistItems" in url:
            data = {"items": [{"snippet": {"title": t, "resourceId": {"videoId": v}}} for v, t in
                              (("AAAAAAAAAAA", "Song One Video Song"), ("BBBBBBBBBBB", "Movie Trailer"), ("CCCCCCCCCCC", "Song Three"))]}
        else:
            data = {"items": [{"id": "AAAAAAAAAAA", "status": {"embeddable": True, "privacyStatus": "public"}, "contentDetails": {"duration": "PT4M"}},
                              {"id": "BBBBBBBBBBB", "status": {"embeddable": True, "privacyStatus": "public"}, "contentDetails": {"duration": "PT2H"}},
                              {"id": "CCCCCCCCCCC", "status": {"embeddable": False, "privacyStatus": "public"}, "contentDetails": {"duration": "PT4M"}}]}
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ch = tmp_path / "ch.txt"
    ch.write_text("# comment\n@ThinkMusicIndia\n")
    out = tmp_path / "idx.csv"
    assert tool.main(["--key", "k", "--channels", str(ch), "--out", str(out)]) == 0
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert [r["video_id"] for r in rows] == ["AAAAAAAAAAA"]          # long video and non-embeddable video left out
    assert tool.main(["--key", "k", "--channels", str(ch), "--out", str(out)]) == 0
    assert len(list(csv.DictReader(open(out, encoding="utf-8")))) == 1   # second run adds nothing twice
