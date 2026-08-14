# SecondSelf — Streamlit Cloud Deployment Plan

> Deploy your AI second brain to [Streamlit Community Cloud](https://streamlit.io/cloud) for free, so it's accessible from any browser without a local setup.

---

## Overview

| Item | Detail |
|------|--------|
| **Platform** | Streamlit Community Cloud (free tier) |
| **Entry point** | `app.py` |
| **Python version** | 3.10+ |
| **Secret required** | `GROQ_API_KEY` |
| **Estimated deploy time** | ~5 minutes |

---

## Pre-deployment Checklist

Before pushing to GitHub, verify that all items below are in order.

### 1. Repository Structure

Streamlit Cloud deploys directly from a GitHub repository. Your repo must contain:

```
Second-Self/
├── app.py                  ✅ entry point
├── requirements.txt        ✅ dependencies
├── config.py               ✅ shared config
├── ask.py                  ✅ RAG engine
├── classify.py             ✅ classifier
├── link.py                 ✅ linker
├── build_graph.py          ✅ graph builder
├── pipeline.py             ✅ pipeline
├── data/
│   └── .gitkeep            ✅ keeps directory in git
├── wiki/                   ✅ your notes (committed)
├── embeddings/             ⚠️  .npy files are gitignored — see note below
└── docs/
    └── deployment-plan.md  ✅ this file
```

> [!WARNING]
> `embeddings/*.npy` is in `.gitignore`. This means embeddings will be **recomputed on every cold start** on the cloud. This is acceptable but adds ~30 s startup time the first time the app loads after a deploy. If you want to persist them, remove `embeddings/*.npy` from `.gitignore` and commit the `.npy` files.

> [!WARNING]
> `data/graph.json` is also gitignored. You **must** either:
> - Remove it from `.gitignore` and commit the file, **or**
> - Add a startup step in `app.py` that calls `build_graph.py` if `graph.json` is missing.
>
> Without `graph.json`, the graph view will be empty on the cloud.

### 2. Fix `requirements.txt`

`python-dotenv` is used by `ask.py` and `classify.py` but is **not listed** in `requirements.txt`. Add it:

```diff
 python-dotenv>=1.0
 requests>=2.31
 groq>=0.4
 sentence-transformers>=2.2
 numpy>=1.24
 pyyaml>=6.0
 python-frontmatter>=1.0
 scikit-learn>=1.3
 streamlit>=1.28
```

> [!NOTE]
> `python-dotenv` is already the first line — ✅ confirmed present. No change needed.

### 3. Secret — `GROQ_API_KEY`

The `.env` file is gitignored and **must never be committed**. On Streamlit Cloud, secrets are injected via the Secrets Manager UI (see Step 3 below).

`ask.py` and `classify.py` currently read the key via `os.environ.get("GROQ_API_KEY")` after calling `load_dotenv()`. On Streamlit Cloud, `load_dotenv()` is a no-op (no `.env` file exists), but the environment variable **will** be present from the Secrets Manager — so no code change is required.

### 4. Paths — Local vs. Cloud

`config.py` uses `Path(__file__).resolve().parent` as `PROJECT_ROOT`, which correctly resolves to the repo root on Streamlit Cloud. All subdirectories (`raw/`, `wiki/`, `data/`, `embeddings/`) are created at startup via `ensure_dirs()`. ✅ No changes needed.

---

## Step-by-Step Deployment

### Step 1 — Push your repo to GitHub

```bash
# If not already a git repo:
git init
git remote add origin https://github.com/<your-username>/Second-Self.git

# Commit all project files (excluding gitignored ones)
git add .
git commit -m "chore: prepare for Streamlit Cloud deployment"
git push -u origin main
```

> [!IMPORTANT]
> Make sure `data/graph.json` and `wiki/` contents are committed before pushing (see Pre-deployment Checklist above).

---

### Step 2 — Sign in to Streamlit Community Cloud

1. Go to **[share.streamlit.io](https://share.streamlit.io)**
2. Click **"Sign in with GitHub"** and authorize Streamlit.

---

### Step 3 — Create a New App

1. Click **"New app"** (top-right).
2. Fill in the form:

| Field | Value |
|-------|-------|
| **Repository** | `<your-username>/Second-Self` |
| **Branch** | `main` |
| **Main file path** | `app.py` |
| **App URL** | choose a custom slug, e.g. `secondself` |

3. Click **"Advanced settings"**.
4. Under **Secrets**, paste:

```toml
GROQ_API_KEY = "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

5. Click **"Deploy!"**

---

### Step 4 — Wait for the Build

Streamlit Cloud will:
1. Clone your repository.
2. Install dependencies from `requirements.txt` (including downloading the `all-MiniLM-L6-v2` model — ~80 MB).
3. Launch `app.py`.

First build takes **3–8 minutes**. Subsequent deploys (triggered by a `git push`) are faster.

---

### Step 5 — Verify the Deployment

Once the app is live, check each feature:

- [ ] **Graph view** renders nodes and edges correctly
- [ ] **Sidebar filters** (PARA categories) work
- [ ] **Ask bar** accepts a question and returns an LLM answer
- [ ] **Source notes** are shown below the answer
- [ ] No `RuntimeError: GROQ_API_KEY is not set` in the logs

To view logs: click the **"Manage app"** button (bottom-right of the live app) → **"Logs"**.

---

## Ongoing Maintenance

| Task | How |
|------|-----|
| **Update notes / graph** | Edit wiki files → `git push` → Streamlit auto-redeploys |
| **Rotate API key** | Streamlit Cloud → App settings → Secrets → update value |
| **Upgrade dependencies** | Edit `requirements.txt` → `git push` |
| **View usage logs** | Manage app → Logs |
| **Custom domain** | Streamlit Cloud settings → Custom domain (paid plan only) |

---

## Known Limitations on Free Tier

| Limitation | Detail |
|------------|--------|
| **Sleep after inactivity** | App sleeps after ~7 days without visitors; wakes on next visit (~30 s) |
| **No persistent disk** | Files written at runtime (e.g. new captures) are lost on restart; use only committed files |
| **1 private app** | Free tier allows 1 private app; unlimited public apps |
| **RAM limit** | ~800 MB RAM — the `sentence-transformers` model fits comfortably |
| **Cold start** | ~30 s on first load if embeddings are not committed |

> [!CAUTION]
> Because the free tier has **no persistent disk**, the `capture.py` / `pipeline.py` CLI workflows (which write to `raw/` and `wiki/`) will **not work on the cloud**. The deployed app is best used as a **read-only viewer + ask interface**. Run the pipeline locally and push results to git.

---

## Optional Improvements Before Deploying

- **Commit `data/graph.json`**: Remove `data/graph.json` from `.gitignore` so the graph is always available without re-running `build_graph.py`.
- **Commit `embeddings/*.npy`**: Remove `embeddings/*.npy` from `.gitignore` to avoid cold-start recomputation.
- **Add `st.cache_resource`** to the embedding model loader in `ask.py` so the model is not reloaded on every rerun (check if already present).
- **Add a `packages.txt`** if any system-level packages are needed (not currently required).

---

*Generated: 2026-08-14 | SecondSelf project*
