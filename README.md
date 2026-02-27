# Winerank Agent

AI-powered wine ranking system that analyzes restaurant wine lists from Michelin-starred establishments worldwide.

## Features

- **Restaurant Crawler**: Scrapes Michelin Guide and restaurant websites to discover and download wine lists
- **Wine List Parser**: Parses wine information from diverse formats using LLM (future component)
- **Wine Ranker**: Ranks wines based on frequency and restaurant quality (future component)
- **DB Manager**: Streamlit-based UI for managing the wine database
- **Web App**: Public-facing web application for wine search and recommendations (future component)

## Architecture

The system is organized into separate components with shared database access:

```
src/winerank/
├── common/          # Shared database models and utilities
├── crawler/         # Restaurant crawler with LangGraph workflow
├── db_manager/      # Streamlit database management UI
├── parser/          # Wine list parser (future)
├── ranker/          # Wine ranking algorithm (future)
└── webapp/          # Consumer web application (future)
```

## Quick Start

### Prerequisites

- Python 3.12+
- Docker (for PostgreSQL)
- uv package manager

### Installation

#### Option 1: Automated Setup (Recommended)

Run the setup script to configure everything automatically:

```bash
chmod +x scripts/setup-dev.sh
./scripts/setup-dev.sh
```

This will install dependencies, Playwright browsers, start PostgreSQL, and initialize the database.

#### Option 2: Manual Setup

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd winerank-agent
```

2. **Install dependencies**
```bash
uv sync
```

3. **Install Playwright browsers** ⚠️ **CRITICAL STEP**
```bash
uv run playwright install chromium
```

4. **Start PostgreSQL**
```bash
docker compose up -d
```

5. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your settings
```

6. **Initialize database**
```bash
uv run winerank db init
```

### Usage

#### Run the Crawler

Crawl 3-star Michelin restaurants (default; uses **USA** site):
```bash
uv run winerank crawl
```
or with sending to a log file:
```bash
uv run winerank crawl 2>&1 | tee crawl.log
```

Crawl a specific **site of record** (default is USA; case-insensitive):
```bash
uv run winerank crawl --site USA --michelin 3
uv run winerank crawl --site Spain --michelin 1
uv run winerank crawl --site "Michelin Guide France" --michelin 2
```
Supported sites (and short names): **Michelin Guide USA** (USA), **Michelin Guide Canada** (Canada), **Michelin Guide Mexico** (Mexico), **Michelin Guide Denmark** (Denmark), **Michelin Guide France** (France), **Michelin Guide Spain** (Spain). `db init` seeds all six; it does not remove existing data.

Crawl specific Michelin levels:
```bash
uv run winerank crawl --michelin 2
uv run winerank crawl --michelin gourmand
```

Crawl a single restaurant (by name or database ID). When using a **name**, the site is used to disambiguate if the same name exists in multiple regions:
```bash
uv run winerank crawl --restaurant "Per Se"
uv run winerank crawl --restaurant 5
uv run winerank crawl --restaurant "Le Bernardin" --site USA
```
Prefer restaurant **ID** when you want to target a specific record (e.g. `--restaurant 5`).

Force re-crawl even if a wine list was already found:
```bash
uv run winerank crawl --restaurant "Per Se" --force
uv run winerank crawl --michelin 3 --force
```

Resume a failed job (`--site` is ignored when resuming):
```bash
uv run winerank crawl --resume 42
```

Check job status:
```bash
uv run winerank crawl-status
```

Register a manually downloaded wine list:
```bash
uv run winerank register-wine-list --restaurant "Smyth"
uv run winerank register-wine-list --restaurant 5 --file ~/Downloads/wine_list.pdf
uv run winerank register-wine-list --restaurant "Le Bernardin" --site USA
```

Use this command when you've manually downloaded a wine list PDF (e.g., from a browser) and want to register it in the database. If `--file` is not specified, the command will look for a PDF in the restaurant's download directory (`data/downloads/<restaurant-slug>/`). This creates the WineList record, extracts text to `.txt`, and marks the restaurant as `WINE_LIST_FOUND`. Use `--site` to disambiguate by name when the same restaurant name exists in multiple regions (e.g. USA vs France).

> **Note**: When both `--restaurant` and `--michelin` are provided, `--restaurant` takes priority and `--michelin` is ignored.

#### SFT Training Data Pipeline

The `winerank sft-data` commands generate a training dataset for supervised fine-tuning of smaller LLMs to parse wine lists. The pipeline uses a cheap **Taxonomy** model to validate and extract wine categories from each list, then a powerful **Teacher** model to parse sampled segments into gold JSON. An optional **Judge** model reviews results; a **correction loop** can re-run the Teacher with Judge feedback to fix issues before building the final dataset.

**Configure in `.env`** (see Configuration below for full list):

```bash
WINERANK_SFT_TAXONOMY_MODEL=gpt-4o-mini
WINERANK_SFT_TEACHER_MODEL=gpt-5.2
WINERANK_SFT_JUDGE_MODEL=claude-4-opus-20250115
WINERANK_SFT_TRAINING_DATA_MODE=vision   # or text
WINERANK_SFT_NUM_SAMPLES=500
WINERANK_SFT_BATCH_MODE=false            # true for 50% cheaper batch API (async)
```

**Run the full pipeline** (init → taxonomy → sample → parse → judge → correction → build):

```bash
uv run winerank sft-data run
```

With batch mode (50% cheaper, async, up to 24h turnaround) and limit to 5 lists for testing:

```bash
uv run winerank sft-data run --batch --limit 5
```

Skip the Judge and correction loop to save cost:

```bash
uv run winerank sft-data run --skip-judge --skip-correction
```

**Run phases individually:**

```bash
uv run winerank sft-data init                  # Generate manifest from data/examples/
uv run winerank sft-data extract-taxonomy      # Phase 1: validate + extract taxonomy
uv run winerank sft-data sample                # Phase 2: sample segments for training
uv run winerank sft-data parse                # Phase 3: Teacher parses segments to JSON
uv run winerank sft-data judge                # Phase 3.5: Judge reviews parsed results
uv run winerank sft-data correct              # Phase 3.6: Correction loop (Teacher + re-judge)
uv run winerank sft-data build                # Phase 4: Assemble JSONL dataset
uv run winerank sft-data stats                # Show progress and dataset summary
```

**Common flags** (apply to `run` and to the relevant phase commands):

| Flag | Description |
|------|-------------|
| `--limit N` | Process only the first N wine lists (reduces lists and segments proportionally) |
| `--batch` / `--no-batch` | Use provider batch APIs (50% cheaper, async) |
| `--dry-run` | Show what would run without calling LLMs |
| `--force` | Re-run completed steps |
| `--skip-judge` | Omit Judge review (run only) |
| `--skip-correction` | Omit correction loop (run only) |
| `--max-correction-rounds N` | Max Teacher correction rounds (default 2; 0 disables) |
| `--mode vision\|text` | Use page images (default) or text only for Teacher and Judge |
| `--seed N` | Random seed for reproducible sampling |
| `--num-samples N` | Target number of segments to sample |
| `--min-judge-score F` | Minimum Judge score to include in dataset (build) |
| `--taxonomy-model`, `--teacher-model`, `--judge-model` | Override models per run |

**Output:** Training data is written to `data/sft/dataset/` (JSONL + metadata). Use the **DB Manager** → **SFT Training Data Review** page to compare original segments, taxonomy, parsed JSON, and Judge results side-by-side.

#### Launch DB Manager

```bash
uv run winerank db-manager
```

The DB Manager UI will open at http://localhost:8501 with pages for:
- **Reports**: Dashboard with metrics and statistics
- **Restaurants**: View and filter restaurant data
- **Wine Lists**: Browse downloaded wine lists
- **Wines**: Search wines (populated by Parser)
- **Jobs**: Monitor crawler jobs
- **Sites of Record**: Manage starting URLs
- **SFT Training Data Review**: Compare original segments, taxonomy, parsed JSON, and Judge results for training data validation

#### Database Management

**Initialize database** (run migrations, safe for existing data):

```bash
uv run winerank db init
```

Use `db init` when:
- Setting up the project for the first time (after PostgreSQL is running)
- Pulling new code that includes schema changes (new migrations)
- Connecting to a fresh or migrated database

It runs Alembic migrations to create or update tables and seeds all six Michelin Guide sites of record (USA, Canada, Mexico, Denmark, France, Spain) if missing. It does **not** delete existing data; new sites are added without removing old ones.

**Stamp database** (set migration version without running migrations):

```bash
uv run winerank db stamp
```

Use `db stamp` when the database schema is already correct but Alembic reports a wrong or missing revision (e.g. after consolidating migrations or switching branches). It sets `alembic_version` to the current head so that the next `db init` runs without revision errors. It does **not** create or change tables.

**When it's safe:** Schema already matches the current migration (e.g. you squashed migrations and the DB was fully migrated, or you fixed the revision table after a restore). **When it's not:** Do *not* run stamp on an empty database (tables would never be created) or when the schema is behind head (you would skip applying migrations and miss new columns/tables).

**Reset database** (destructive – wipes all data):

```bash
uv run winerank db reset
uv run winerank db reset -y   # skip confirmation
```

Use `db reset` only when you want to start from scratch (e.g. after a failed crawl, for a clean test run, or when debugging). It drops all tables, recreates them, and re-seeds initial data.

## Configuration

Edit `.env` to configure:

```bash
# Database
WINERANK_DATABASE_URL=postgresql+psycopg://winerank:winerank@localhost:5432/winerank

# Crawler Settings
WINERANK_MICHELIN_LEVEL=3                    # 3, 2, 1, gourmand, selected, all
WINERANK_RESTAURANT_WEBSITE_DEPTH=4          # Max link depth
WINERANK_MAX_RESTAURANT_PAGES=20             # Max pages per restaurant
WINERANK_CRAWLER_CONCURRENCY=3               # Parallel restaurant processing

# LLM Settings (for intelligent wine list discovery)
WINERANK_LLM_PROVIDER=openai                 # openai, anthropic, gemini, etc.
WINERANK_LLM_MODEL=gpt-4o-mini               # Model name
WINERANK_LLM_API_KEY=your-api-key-here       # Required for LLM features
WINERANK_USE_LLM_NAVIGATION=true             # Enable LLM-assisted navigation
WINERANK_LLM_TEMPERATURE=0.0                 # Temperature (0.0 = deterministic)
WINERANK_LLM_MAX_TOKENS=500                  # Max tokens per response

# Playwright
WINERANK_HEADLESS=true                       # Run browser in headless mode (set false if a site returns 403 on wine-list downloads)
WINERANK_BROWSER_TIMEOUT=30000               # Browser timeout (ms)

# SFT Training Data Pipeline (winerank sft-data)
WINERANK_SFT_TAXONOMY_MODEL=gpt-4o-mini      # Cheap model for taxonomy extraction
WINERANK_SFT_TEACHER_MODEL=gpt-5.2                  # Teacher for gold wine parsing
WINERANK_SFT_JUDGE_MODEL=claude-4-opus-20250115     # Optional judge for quality review
WINERANK_SFT_TRAINING_DATA_MODE=vision       # vision or text
WINERANK_SFT_NUM_SAMPLES=500                 # Target segments for training set
WINERANK_SFT_SEED=42                         # Random seed for sampling
WINERANK_SFT_BATCH_MODE=false                # true = batch API (50% cheaper, async)
WINERANK_SFT_BATCH_TIMEOUT=86400             # Max seconds to wait for batch (default 24h)
WINERANK_SFT_MAX_CORRECTION_ROUNDS=2         # Teacher correction rounds (0 = disabled)
```

## Wine List Discovery

The crawler uses a multi-strategy approach to find wine lists on restaurant websites:

### Cached URL Verification
If a wine list URL was previously found, verify and reuse it (fastest path).

### Smart Keyword Search
Enhanced keyword matching with **link-context analysis** — inspects not just link text and URL, but also the surrounding paragraph text. This catches patterns like "The current version of the wine list is available *here*" where the link text itself ("here") contains no keywords.

Keywords are derived from analysis of 14+ Michelin-starred restaurant websites (Per Se, French Laundry, Le Bernardin, Jungsik, Eleven Madison Park, Atelier Crenn, Smyth, and more):
- **Wine-specific** (30 terms): "wine list", "wine & cocktails", "wine & spirits", "wine selections", "beverage program", "bar menu", "cocktail menu", "spirits selections", etc.
- **Menu/navigation** (11 terms): "menus", "menus & stories", "dining", "the experience", etc.

The crawler supports **English, French, and Spanish** restaurant sites. For Michelin France, Spain, and Mexico, keyword lists and LLM guidance include localized terms (e.g. "Carte des vins", "Carta de vinos", "Carte des boissons", "Lista de vinos"). The language hint is derived from the restaurant's country: **France** → French; **Spain** and **Mexico** → Spanish; all others (USA, Canada, Denmark, etc.) → English.

PDFs are scored by relevance (wine-related filenames score higher; catering decks are penalized). Irrelevant links (social media, careers, reservations, etc.) are automatically filtered out.

### LLM-Guided Search
When enabled (via `WINERANK_USE_LLM_NAVIGATION=true`), the crawler uses AI to intelligently pick which links to follow. The LLM receives a compact page summary (navigation links + text snippets) to stay economical with tokens (~300-400 per call, max 2 calls per restaurant).

### SPA / Dynamic Page Handling
Wine lists hosted on JavaScript-rendered platforms (e.g. Binwise digital menus) are automatically detected. The downloader uses Playwright to render the page, clicks interactive tabs (e.g. "Wine List", "Carte des vins", "Carta de vinos") to expand full content, and captures the rendered DOM — ensuring complete wine data is downloaded even from React/Vue/Angular SPAs.

### Crawl Metrics

The crawler tracks detailed metrics for each restaurant:
- **crawl_duration_seconds**: Time taken to search the restaurant's website
- **llm_tokens_used**: Number of LLM tokens consumed (for cost tracking)
- **pages_visited**: Number of pages explored during the search

These metrics help you optimize performance, track LLM API costs, and understand success patterns.

## Database Schema

- **SiteOfRecord**: Starting points for crawling (e.g., Michelin Guide)
- **Restaurant**: Restaurant details with crawl metadata
- **WineList**: Downloaded wine lists with file hashes
- **Wine**: Parsed wine entries (populated by Parser)
- **Job**: Crawler job tracking with checkpointing

## Development

### Run Tests

**Unit tests** (fast, no network, run by default):

```bash
uv run pytest
uv run pytest -v                           # verbose output
uv run pytest tests/test_models.py         # single module
```

**Integration tests** (hit live websites and LLM APIs, skipped by default):

```bash
uv run pytest tests/integration/ -v -m integration          # all integration tests
uv run pytest tests/integration/test_wine_list_finder.py -v -m integration   # wine list finder only
uv run pytest tests/integration/ -v -m integration -k Smyth  # single restaurant
```

Integration tests require Playwright browsers installed (`uv run playwright install chromium`) and, for LLM-assisted tests, a valid `WINERANK_LLM_API_KEY` in `.env`.

**All tests** (unit + integration):

```bash
uv run pytest -v -m ""                     # override the default marker filter
```

### Project Structure

```
winerank-agent/
├── alembic/                 # Database migrations
├── data/
│   ├── examples/            # Sample wine list PDFs
│   └── downloads/           # Crawler output
├── scripts/
│   └── setup-dev.sh         # Development environment setup
├── src/winerank/            # Main package
├── tests/                   # Test suite
├── docker-compose.yml       # PostgreSQL setup
├── Dockerfile               # Production container image
├── DEPLOYMENT.md            # Detailed deployment guide
├── pyproject.toml           # Dependencies
└── README.md
```

## Crawler Workflow

The crawler uses LangGraph with PostgreSQL checkpointing for reliable stop/resume:

1. **Init Job** — Create or resume crawler job
2. **Fetch Listing** — Scrape Michelin listing pages (or load a single restaurant from DB)
3. **Process Restaurant** — Extract restaurant details; skip if wine list already found (unless `--force`)
4. **Crawl Site** — Navigate restaurant website to find wine list (keyword search + optional LLM)
5. **Download** — Download wine list file (PDF/HTML); auto-detect and render JS-rendered SPAs via Playwright
6. **Extract Text** — Convert to structured text (pdfplumber for PDFs, smart HTML extraction for web pages)
7. **Save Result** — Update database with crawl status and metrics
8. **Complete Job** — Mark job as complete with summary statistics

## Deployment

For detailed deployment instructions (development and production), see [DEPLOYMENT.md](DEPLOYMENT.md).

### Quick Deployment Overview

**Local Development**: Use `./scripts/setup-dev.sh` for automated setup.

**Production**:
- **Docker**: Use the provided `Dockerfile` for containerized deployment
- **VM**: Follow the manual setup steps with production database
- **Critical**: Always run `uv run playwright install chromium` after dependency installation

See [DEPLOYMENT.md](DEPLOYMENT.md) for:
- Step-by-step production deployment guides
- Docker and VM deployment options
- Environment configuration
- Troubleshooting common issues
- Monitoring and scaling strategies

## Roadmap

- [x] Database schema and models
- [x] DB Manager UI (Streamlit)
- [x] Restaurant crawler with Playwright
- [x] Wine list downloader and text extraction
- [x] LangGraph workflow with checkpointing
- [x] Smart skip logic (don't re-crawl restaurants with wine lists already found)
- [x] Single-restaurant crawl (`--restaurant` option)
- [x] SPA / dynamic page rendering (Binwise, React apps, etc.)
- [x] Crawl metrics tracking (duration, pages visited, LLM tokens)
- [ ] Wine List Parser with LLM
- [ ] Wine Ranker algorithm
- [ ] Consumer Web App
- [ ] API for wine search
- [ ] Automated crawler scheduling

## License

MIT

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
