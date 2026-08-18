# Deployment Guide

Two parts: getting the code onto GitHub, then deploying it on Render.

---

## Part 1 — Push to GitHub

### 1. Create the repo on GitHub

Go to [github.com/new](https://github.com/new), create a new **empty**
repository (don't initialize with a README/.gitignore — this project
already has both). Copy the URL it gives you, e.g.:

```
https://github.com/<your-username>/ai-voice-assistant.git
```

### 2. Initialize git locally (if you haven't already)

From the project root (the folder containing `backend/`, `frontend/`,
`README.md`):

```bash
cd ai-voice-assistant
git init
git add .
git status
```

**Before committing**, check `git status` doesn't show a `.env` file. This
project's `.gitignore` already excludes `.env` (only `.env.example` is
tracked), but it's worth a glance — a committed API key is very hard to
fully scrub from git history after the fact.

```bash
git commit -m "Initial commit: Phases 1-5 (foundation through learning analysis)"
```

### 3. Connect and push

```bash
git branch -M main
git remote add origin https://github.com/<your-username>/ai-voice-assistant.git
git push -u origin main
```

If you're prompted for a password, GitHub no longer accepts your account
password over HTTPS — use a [personal access token](https://github.com/settings/tokens)
instead, or push over SSH.

### 4. Updating later (subsequent phases, bug fixes, etc.)

```bash
git add .
git status               # sanity check what's staged
git commit -m "Describe what changed"
git push
```

### If you already have a git repo and are just updating it

```bash
git add .
git status                        # confirm no .env, no __pycache__, etc.
git commit -m "Phase 5: learning analysis"
git push
```

If `git status` shows files you don't want tracked (e.g. a stray `.env`
that got committed previously), see [Appendix: removing a
previously-committed secret](#appendix-removing-a-previously-committed-secret)
below.

---

## Part 2 — Host on Render

This repo includes `render.yaml` (a Render "Blueprint") and
`backend/Dockerfile`, so Render can build and deploy it automatically —
you mostly just need to provide the secrets.

### Prerequisite: MongoDB

Render doesn't offer managed MongoDB directly. The easiest free option is
**MongoDB Atlas**:

1. Go to [mongodb.com/cloud/atlas/register](https://www.mongodb.com/cloud/atlas/register), create a free account.
2. Create a free **M0** cluster (any region close to your Render region).
3. **Database Access** → add a database user (username + password — save these).
4. **Network Access** → add IP address `0.0.0.0/0` ("allow access from
   anywhere"). Render's outbound IPs aren't static on free/starter plans,
   so this is the practical option for a single-user hobby project like
   this one. If that makes you uneasy, Atlas also supports IP allowlists
   tied to Render's static outbound IP add-on (paid) — see Render's docs
   on "Static Outbound IPs" if you want that instead.
5. **Database** → **Connect** → **Drivers** → copy the connection string.
   It looks like:
   ```
   mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
   Replace `<username>`/`<password>` with the ones from step 3. This full
   string is your `MONGODB_URI`.

### Deploy the Blueprint

1. Push your code to GitHub (Part 1 above) if you haven't.
2. Go to the [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**.
3. Connect your GitHub account if prompted, then select this repository.
4. Render reads `render.yaml` and shows you the `ai-voice-assistant` web
   service it's about to create. Click through to create it.
5. Render will ask you to fill in the environment variables marked
   `sync: false` in `render.yaml` — these are the secrets it deliberately
   didn't put in the file:

   | Variable | Value |
   |---|---|
   | `MONGODB_URI` | The Atlas connection string from above |
   | `GEMINI_API_KEY` | Your Gemini API key |
   | `GEMINI_MODEL` | Leave blank to use the default, or set e.g. `gemini-2.0-flash` |
   | `NVIDIA_API_KEY` | Your NVIDIA API key (optional — leave blank if you're only using Gemini) |
   | `NVIDIA_MODEL` | Leave blank for the default |
   | `NVIDIA_BASE_URL` | Leave blank for the default |
   | `CORS_ORIGINS` | Leave blank for now — see step 7 |

6. Click **Apply** / **Create Web Service**. Render builds the Docker
   image (this takes a few minutes the first time) and deploys it.
7. Once deployed, Render gives you a URL like
   `https://ai-voice-assistant-xxxx.onrender.com`. Go back to your
   service's **Environment** tab and set `CORS_ORIGINS` to that exact URL
   (no trailing slash), then save — this triggers a redeploy. This step
   matters: without it, the browser will block the frontend's own API
   calls due to CORS.
8. Visit the URL. You should see the Vaani console. Click the mic button
   and grant microphone permission — note that `getUserMedia` (microphone
   access) requires HTTPS, which Render gives you automatically, so this
   should just work.

### Setting env vars manually (without the Blueprint)

If you'd rather create the service by hand instead of via `render.yaml`:

1. **New** → **Web Service** → connect the repo.
2. **Runtime**: Docker. **Dockerfile Path**: `backend/Dockerfile`.
   **Docker Build Context Directory**: `.` (repo root — this matters,
   since the Dockerfile copies both `backend/` and `frontend/`).
3. **Health Check Path**: `/api/health`.
4. Add the same environment variables listed in the table above, plus the
   non-secret ones from `render.yaml`'s `envVars` list (`APP_ENV=production`,
   `ENABLE_API_DOCS=false`, etc.).

### Verifying it worked

```bash
curl https://<your-app>.onrender.com/api/health
curl https://<your-app>.onrender.com/api/health/ready
```

`/api/health/ready` should show `"mongodb": "ok"` and
`"gemini_configured": true` (and/or `nvidia_configured: true`). If
`mongodb` shows `"unavailable"`, double check the Atlas connection string
and that Network Access allows Render's traffic.

### Notes on the free/starter plan

- Render's free web services spin down after inactivity and take ~30-60s
  to wake up on the next request — the first request after idle time will
  be slow. This is a Render platform behavior, not something in this
  project's control.
- `MAX_CONVERSATION_MINUTES` and `MAX_DAILY_AI_REQUESTS` (already
  configurable via env vars, see `backend/.env.example`) exist specifically
  to cap AI API spend — worth double-checking those values are set the way
  you want for a publicly-reachable deployment.

### Troubleshooting the build

**`Failed building wheel for webrtcvad` / `gcc: No such file or directory`**
`webrtcvad` (used for voice activity detection, Phase 3) ships as a C
extension with no prebuilt wheel for every platform, so it compiles from
source at install time. `backend/Dockerfile` handles this with a
multi-stage build — a throwaway "builder" stage installs `gcc` and
compiles everything, then only the compiled packages (not the compiler)
get copied into the slim runtime image. If you see this error, you're
likely on an older copy of the Dockerfile from before this was fixed —
pull the latest `backend/Dockerfile` and redeploy (Render → **Manual
Deploy** → **Clear build cache & deploy** to make sure the old layer
isn't reused).

---

## Appendix: removing a previously-committed secret

If a real API key ever ends up in a commit, changing the file afterward
isn't enough — it's still in git history. The two practical fixes:

1. **Rotate the key.** Generate a new API key from Google AI
   Studio/NVIDIA and revoke the old one. This is the fast, reliable fix —
   do this regardless of whether you also clean history.
2. **Clean history** (optional, if the repo is public and you want the old
   key gone from history too): use [`git filter-repo`](https://github.com/newren/git-filter-repo)
   or GitHub's [guide on removing sensitive
   data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
   Rotating the key (step 1) matters more than this step, since the key
   may already be cached/scraped once pushed publicly.
