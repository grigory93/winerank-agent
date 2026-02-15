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

Crawl 3-star Michelin restaurants (default):
```bash
uv run winerank crawl
```

Crawl specific Michelin levels:
```bash
uv run winerank crawl --michelin 2
uv run winerank crawl --michelin gourmand
```

Resume a failed job:
```bash
uv run winerank crawl --resume 42
```

Check job status:
```bash
uv run winerank crawl-status
```

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

#### Database Management

Reset database (destructive!):
```bash
uv run winerank db reset
```

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

# Playwright
WINERANK_HEADLESS=true                       # Run browser in headless mode
WINERANK_BROWSER_TIMEOUT=30000               # Browser timeout (ms)
```

## Database Schema

- **SiteOfRecord**: Starting points for crawling (e.g., Michelin Guide)
- **Restaurant**: Restaurant details with crawl metadata
- **WineList**: Downloaded wine lists with file hashes
- **Wine**: Parsed wine entries (populated by Parser)
- **Job**: Crawler job tracking with checkpointing

## Development

### Run Tests

```bash
uv run pytest
```

Test specific modules:
```bash
uv run pytest tests/test_models.py
uv run pytest tests/test_text_extractor.py
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

1. **Init Job** - Create or resume crawler job
2. **Fetch Listing** - Scrape Michelin listing pages
3. **Process Restaurant** - Extract restaurant details
4. **Crawl Site** - Navigate restaurant website to find wine list
5. **Download** - Download wine list file (PDF/HTML)
6. **Extract Text** - Convert to structured text with pdfplumber
7. **Save Result** - Update database with results
8. **Complete Job** - Mark job as complete

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
- [ ] Wine List Parser with LLM
- [ ] Wine Ranker algorithm
- [ ] Consumer Web App
- [ ] API for wine search
- [ ] Automated crawler scheduling

## License

MIT

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
