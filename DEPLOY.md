# Deploying CascadeLens (free)

The prototype is a FastAPI app that also serves its own HTML dashboard. It is stateless
and needs no database or API keys, so it runs on free tiers.

| Target | Cost | Sleeps when idle? | Notes |
| --- | --- | --- | --- |
| **Vercel** (recommended, matches the architecture diagram) | Free Hobby plan | No | Runs FastAPI as a Python serverless function |
| **Render** | Free | Yes (~30-50 s wake-up) | Classic always-on server; simplest mental model |
| **Local / LAN** | Free | - | For demos on one laptop or a venue Wi-Fi |

Files already in the repo for this: `api/index.py` (Vercel entry point), `vercel.json`
(routes everything to it), `.vercelignore`, `requirements.txt`.

---

## Option A - Vercel via the website (no CLI, ~3 minutes)

1. Go to <https://vercel.com/signup> and choose **Continue with GitHub**.
   Use a GitHub account that has access to the repo.
2. Click **Add New... -> Project**.
3. Under **Import Git Repository**, pick `cascadelens`. If it is not listed, click
   **Adjust GitHub App Permissions** and grant access to that repository.
4. Leave every setting at its default:
   - Framework Preset: **Other**
   - Root Directory: `./`
   - Build Command / Output Directory: empty
   - Environment Variables: none needed
5. Click **Deploy**. The first build takes about a minute.
6. Open the URL Vercel shows (`https://cascadelens-<something>.vercel.app`).

From now on **every push to `main` redeploys automatically**; pull requests get their own
preview URLs.

### Verify

- `/` shows the dashboard and the default S1 scenario runs on load.
- `/api/network` returns JSON with 20 assets.
- `/docs` shows the FastAPI Swagger UI.
- Click **Compare interventions** - the ranked table and explanation appear.

### Custom name

**Project -> Settings -> Domains -> Edit** lets you change the free domain, for example
`cascadelens.vercel.app` if it is unclaimed.

---

## Option B - Vercel via CLI

```powershell
cd cascadelens
npx vercel@latest login          # opens a browser device-code page; approve it
npx vercel@latest link           # link this folder to a new Vercel project (accept defaults)
npx vercel@latest --prod         # deploy to production and print the URL
```

Later deployments: just `git push` (if the project is linked to GitHub) or run
`npx vercel@latest --prod` again.

Useful commands:

```powershell
npx vercel@latest ls             # list deployments
npx vercel@latest logs <url>     # tail function logs
npx vercel@latest inspect <url>  # build details
```

---

## Option C - Render (always-on style server)

1. <https://render.com> -> **Sign up with GitHub**.
2. **New -> Web Service -> Build and deploy from a Git repository** -> select `cascadelens`.
3. Settings:
   - Runtime: **Python 3**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Instance type: **Free**
4. **Create Web Service**. URL: `https://cascadelens.onrender.com` (or similar).

Free instances sleep after 15 minutes without traffic. Open the URL a minute before a
demo so it is awake.

---

## Option D - Run locally for a live demo

```powershell
cd cascadelens
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Same laptop: <http://127.0.0.1:8000>
- Other devices on the same Wi-Fi: `http://<your-laptop-ip>:8000`
  (find the IP with `ipconfig`; allow Python through Windows Firewall when prompted).

---

## Pre-deploy checklist

```powershell
.\.venv\Scripts\python -m pytest -q      # expect: 93 passed
git status                               # clean working tree
git push origin main
```

## How the Vercel setup works

- `vercel.json` rewrites every path to `/api/index`.
- `api/index.py` imports the FastAPI `app` from `app/main.py`; Vercel detects the ASGI
  app and serves it as a Python function.
- `static/index.html` is read from the function bundle, so the dashboard and API share
  one deployment and one origin (no CORS setup needed).
- `.vercelignore` keeps `.venv`, tests and screenshots out of the bundle.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Build fails on a Python version error | Vercel uses Python 3.12 by default; the code targets 3.10+. Check the build log for the failing package. |
| `404 NOT_FOUND` on `/` | Confirm `vercel.json` is at the repo root and Root Directory in project settings is `./`. |
| `500` on API calls but `/` works | Open **Deployments -> latest -> Functions** for the traceback. |
| Repo not visible in Vercel import list | GitHub app permissions - grant Vercel access to `cascadelens`. |
| Render URL takes ~40 s | Free instance waking up; expected. |

## Limits to remember

- Free tiers are for demos and small teams; no uptime guarantee.
- The prototype keeps nothing between requests. Adding Supabase persistence or Groq
  explanations later means setting those keys as **Environment Variables** in the
  Vercel project settings, never in the repo.
