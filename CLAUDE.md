# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## SeaSussed

A Chrome extension + Cloud Run backend that uses Gemini 2.5 Flash to analyze grocery product page screenshots and provide real-time seafood sustainability scores. Built for the Gemini Live Agent Challenge (UI Navigator category). Submission deadline: **March 16, 2026**.

## Stack

- **Backend:** Python 3.13, FastAPI, Google ADK v1.17, Gemini 2.5 Flash (Vertex AI)
- **Extension:** Chrome Manifest V3, Vanilla JS (no build step — keep it simple for hackathon)
- **Data:** SQLite built from FishBase (Parquet) + MSC CSV + NOAA FishWatch, deployed with backend
- **Infrastructure:** Google Cloud Run (us-central1), Artifact Registry, Vertex AI

## Key Commands

```bash
# Backend (run from backend/)
uv sync                              # Install dependencies
uv run python -m scripts.build_database  # One-time: build data/seafood.db (gitignored)
uv run uvicorn main:app --reload     # Local dev server (port 8000)
uv run pytest                        # Run all tests
uv run pytest tests/test_health.py  # Run a single test file
uv run ruff check --fix .            # Auto-fix lint
uv run mypy .                        # Type check

# Run ALL verification sequentially before every commit (NEVER in parallel):
cd /Users/jordan/sussed/backend && uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest 2>&1

# Cloud Run deployment (GCP project: seasussed-489008)
gcloud run deploy seasussed-backend \
  --source backend/ \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --min-instances 1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=seasussed-489008,GOOGLE_CLOUD_REGION=us-central1

# Chrome Extension
# Load unpacked: chrome://extensions → Load unpacked → select extension/
# Set BACKEND_URL in extension/config.js to your Cloud Run URL
```

### Local Dev Environment Variables

Set these before running the backend locally (required for Vertex AI auth):

```bash
export GOOGLE_CLOUD_PROJECT=seasussed-489008
export GOOGLE_CLOUD_REGION=us-central1
# Auth: gcloud auth application-default login
```

## TDD Workflow

**Tests are written before implementation.** No code is committed without passing tests.

Rules:
1. Write the test first — it must fail before writing the implementation
2. Write the minimum implementation to make the test pass
3. Run the full suite (`mypy` + `ruff` + `pytest`) before every commit — enforced by pre-commit hook
4. Never commit with failing tests or type errors
5. If a bug is found, write a test that reproduces it before fixing it

The pre-commit hook at `.githooks/pre-commit` runs all three checks automatically.
New contributors must run once to activate it:
```bash
git config core.hooksPath .githooks
```

## RPI Workflow

All significant changes follow four phases, each in its own conversation:
1. `/research` — document the codebase as-is (documentarian mode only)
2. `/plan` — create a phased implementation spec
3. `/implement` — one phase at a time, stop after each for human confirmation
4. `/validate` — verify against the plan

Use `/compact` when context is heavy. Use `/clear` between unrelated tasks.

## Project Structure

Target structure (phases 1–3 establish this layout):

```
seasussed/
├── backend/              # Python FastAPI + ADK service
│   ├── main.py           # FastAPI entry: GET /health, POST /analyze
│   ├── models.py         # Pydantic: AnalyzeRequest, SustainabilityScore, ProductInfo
│   ├── database.py       # SQLite query functions
│   ├── agents/
│   │   ├── pipeline.py           # SequentialAgent wiring both sub-agents
│   │   ├── screen_analyzer.py    # Gemini vision: screenshot → ProductInfo
│   │   └── sustainability_scorer.py  # Gemini + DB tools → SustainabilityScore
│   ├── data/             # seafood.db (gitignored — run build_database.py first)
│   ├── scripts/          # build_database.py (FishBase + MSC + NOAA ingest)
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml    # uv-managed
├── extension/            # Chrome Manifest V3 extension
│   ├── manifest.json
│   ├── config.js         # BACKEND_URL — set this to your Cloud Run URL
│   ├── background.js     # Service worker: captureVisibleTab + POST /analyze
│   ├── content_script.js # Injected into product pages, renders score overlay
│   ├── popup.html/js     # Extension popup UI
│   └── icons/
├── docs/
│   ├── research/         # YYYY-MM-DD-description.md
│   ├── plans/            # YYYY-MM-DD-description.md + phases/ subdirs
│   └── decisions/        # Architecture decision records
└── .claude/
    ├── settings.json
    └── commands/
```

## Sustainability Scoring Model

Five categories, each scored independently, total 0–100:

| Category | Wild-Caught | Farmed | Key Data Source |
|---|---|---|---|
| Biological & Population Status | 20 pts | 20 pts | FishBase vulnerability, resilience, IUCN |
| Fishing & Harvesting Practices | 25 pts | — | Gear type lookup table |
| Aquaculture & Farming Practices | — | 25 pts | ASC/BAP cert, species feed type |
| Management & Regulation | 30 pts | 30 pts | MSC cert, NOAA status, country score |
| Environmental & Ecological | 25 pts | 25 pts | FishBase trophic, IUCN, bycatch risk |

Grade: A (80–100) = Best Choice 🟢 | B (60–79) = Good Alternative 🟡 | C (40–59) = Use Caution 🟠 | D (0–39) = Avoid 🔴

## Agent Architecture

```
Chrome Extension
  captureVisibleTab() → base64 PNG
  POST /analyze → Cloud Run

Cloud Run (FastAPI + ADK SequentialAgent)
  1. ScreenAnalyzerAgent  (gemini-2.5-flash, vision)
       → extracts species, origin, method, certifications from screenshot
  2. SustainabilityScorerAgent (gemini-2.5-flash + DB tools)
       → scores species, selects 3 alternatives
       → tools: query_species_db, query_msc_db, query_noaa_db, find_alternatives

Returns: { score, grade, breakdown, alternatives, explanation }
```

## API Contract

`POST /analyze` — the only endpoint the extension calls. Defined in `backend/models.py`.

```
Request:  { screenshot: string (base64 PNG), url: string, page_title?: string }

Response: {
  score: int (0–100),
  grade: "A"|"B"|"C"|"D",
  breakdown: { biological: float, practices: float, management: float, ecological: float },
  alternatives: [{ species, score, grade, reason }],  // always 3
  explanation: string,  // 2–3 sentences
  product_info: { is_seafood: bool, species, wild_or_farmed, fishing_method, origin_region, certifications }
}
```

If `is_seafood` is false, the full response still uses this shape with `score: 0`.

---

## Agent Operational Rules

### Shell & Tools
- Chain verification commands sequentially: `mypy 2>&1; ruff check 2>&1; pytest 2>&1`
- In worktrees: prefix every command with `cd /absolute/path/to/worktree &&`
- Never use `~` in file tool paths — use `/Users/jordan/sussed/...`

### Git
- `git pull --rebase` before every push
- Pre-commit hook runs mypy + ruff + pytest automatically — never bypass with `--no-verify`
- Worktree cleanup: `git worktree remove --force <path>; git branch -D <branch>`
- **NEVER commit secrets** — API keys, service account JSON, private keys, tokens, passwords must never appear in committed files. Use environment variables or ADC instead.
- Before staging files, scan for secrets: reject any file matching `*.key`, `*.pem`, `*.p12`, `service-account*.json`, `credentials*.json`, `gcp-key*.json`, or any hardcoded key/token string.
- If a secret is accidentally staged, stop immediately and tell the user to rotate the credential before pushing.

### Python-Specific
- Always use `uv run python` — never bare `python3`
- Use `python -m scripts.foo` for scripts with package-relative imports
- Inspect JSON structure before indexing (check `type(data)` first)
- `ruff check --fix` before manually editing lint issues

### Cloud Run / GCP
- API key never in extension source — all Gemini calls go through Cloud Run backend
- Use Vertex AI (not AI Studio) for hackathon demo to avoid rate limits
- Keep `--min-instances 1` during demo to avoid cold starts

## Git Workflow

Two branches:
- `main` — stable, deployable. Only merge from `dev` via PR when a phase is complete and verified.
- `dev` — active development. All day-to-day work happens here.

Typical flow:
1. Work on `dev` with conventional commits
2. When a phase is complete and passing (`mypy` + `ruff` + `pytest`), open a PR `dev → main`
3. Merge PR, then `git pull --rebase` on both branches

Use conventional commits:
```
feat(scope): description
fix(scope): description
chore: description
docs: description
```

## Hackathon Submission Requirements

- [ ] Public GitHub repo with spin-up instructions
- [ ] Google Cloud deployment (Cloud Run) — proof via screen recording or code link
- [ ] Architecture diagram
- [ ] Demo video ≤ 4 minutes showcasing real-time multimodal features
- [ ] Devpost submission before March 16, 2026 5:00 PM PDT

## Document Storage

- Research: `docs/research/YYYY-MM-DD-description.md`
- Plans: `docs/plans/YYYY-MM-DD-description.md`
- Phase files: `docs/plans/YYYY-MM-DD-description-phases/phase-N.md`
