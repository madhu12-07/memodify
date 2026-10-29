# Hosting Memodify (Render / Railway / any Python host)

Files added for hosting: `wsgi.py`, `Procfile`, `runtime.txt`, `gunicorn` in `requirements.txt`.

## Environment variables (set these on the host, never commit `.env`)

| Name | Value |
|------|-------|
| `APP_ENV` | `production` (secure cookies, correct client IP behind the host's proxy) |
| `SECRET_KEY` | long random text: `python -c "import secrets;print(secrets.token_hex(32))"` |
| `ADMIN_USERNAME` | your admin name |
| `ADMIN_PASSWORD` | a LONG password (admin stays disabled while empty) |
| `YOUTUBE_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | same as your local `.env` |

## Render (easiest)
1. Push the project to GitHub (`.env` and `instance/` are already in `.gitignore`).
2. Render -> New -> Web Service -> pick the repo.
3. Build command: `pip install -r requirements.txt`  Start command: `gunicorn wsgi:app --workers 2 --threads 4 --bind 0.0.0.0:$PORT`
4. Add the environment variables above.
5. **Add a Persistent Disk** and set `DATABASE` folder there, or users/favorites vanish on every redeploy
   (the app stores them in `instance/manaisai.db`; mount the disk at `/opt/render/project/src/instance`).

## After it is live
* Google sign-in: add your live `https://your-domain` under *Authorized JavaScript origins* in Google Cloud.
* The camera (face mood) works only on https, which Render/Railway give you automatically.
* Admin panel: `https://your-domain/admin/login` (not linked in the user menu; the login page has a small "Admin sign in" link).
