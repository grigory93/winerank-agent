# Deployment Configuration Updates - Feb 14, 2026

## Summary

Fixed Playwright browser installation issue and created comprehensive deployment documentation to ensure proper setup in dev and production environments.

## Issue Resolved

**Problem**: Crawler failed with error:
```
BrowserType.launch: Executable doesn't exist at .../chromium_headless_shell-1208/...
Looks like Playwright was just installed or updated.
Please run the following command to download new browsers:
    playwright install
```

**Root Cause**: Playwright browsers were not installed after dependency installation.

**Solution**: 
- Installed Playwright browsers: `uv run playwright install chromium`
- Created automated setup scripts and deployment documentation

## Files Created

### 1. `scripts/setup-dev.sh` (NEW)
Automated development environment setup script that:
- Verifies prerequisites (uv, Docker)
- Installs Python dependencies
- **Installs Playwright browsers** ✅
- Starts PostgreSQL
- Creates .env file
- Initializes database

### 2. `Dockerfile` (NEW)
Production-ready Docker image that:
- Uses Python 3.12-slim base image
- Installs system dependencies for Playwright
- Installs uv package manager
- Installs Python dependencies
- **Installs Playwright browsers and deps** ✅
- Includes health check

### 3. `.dockerignore` (NEW)
Optimizes Docker build by excluding unnecessary files.

### 4. `DEPLOYMENT.md` (NEW)
Comprehensive deployment guide covering:
- Prerequisites for dev and prod
- Automated and manual setup instructions
- Docker deployment (AWS ECS, Google Cloud Run)
- VM deployment with systemd service
- Database setup (RDS, Neon, Supabase)
- Environment configuration
- **Troubleshooting section** including Playwright issues
- Monitoring and scaling strategies

### 5. `scripts/README.md` (NEW)
Documentation for utility scripts.

## Files Updated

### 1. `README.md`
- Added automated setup option (recommended)
- Marked Playwright installation as **CRITICAL STEP**
- Updated deployment section to reference DEPLOYMENT.md
- Updated project structure to include new files

### 2. `docker-compose.yml`
- Added optional crawler service configuration
- Added optional DB Manager service configuration
- Improved for production deployment scenarios

### 3. `src/winerank/crawler/workflow.py`
- Fixed PostgresSaver initialization (previously fixed)
- Changed from Engine object to connection string

## Verification

✅ Playwright browsers installed (chromium v1208)
✅ Setup script created and made executable
✅ Dockerfile includes Playwright installation
✅ Documentation covers all deployment scenarios
✅ Troubleshooting guide includes Playwright issues

## Usage

### For Development (New Setup)
```bash
./scripts/setup-dev.sh
```

### For Development (Existing Setup)
```bash
uv run playwright install chromium
uv run winerank crawl --michelin 3
```

### For Production (Docker)
```bash
docker build -t winerank-agent:latest .
docker run -e WINERANK_DATABASE_URL="..." winerank-agent:latest uv run winerank crawl
```

### For Production (VM)
```bash
uv sync
uv run playwright install chromium
uv run playwright install-deps  # System dependencies
uv run winerank db init
uv run winerank crawl --michelin 3
```

## Next Steps

1. Test the setup script on a clean development environment
2. Test Docker build and deployment
3. Update CI/CD pipeline to include `playwright install` step
4. Consider adding Playwright browser installation to GitHub Actions workflows
5. Document any additional environment-specific requirements

## Key Takeaways

**Critical Steps for Any Environment:**
1. Install Python dependencies
2. **Install Playwright browsers** ← Don't skip this!
3. Configure database connection
4. Initialize database schema

**Why This Matters:**
- Playwright browsers are ~250MB and must be explicitly installed
- Browser versions must match the Playwright package version
- System dependencies vary by OS (handled in Dockerfile)
- Forgetting this step causes immediate crawler failure

## References

- [Playwright Installation Docs](https://playwright.dev/python/docs/browsers)
- [LangGraph Checkpoint Postgres](https://langchain-ai.github.io/langgraph/)
- New file: `DEPLOYMENT.md` for comprehensive deployment guide
