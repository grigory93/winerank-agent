# Winerank Agent - Deployment Guide

This guide covers deploying Winerank Agent in development and production environments.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Development Deployment](#development-deployment)
- [Production Deployment](#production-deployment)
- [Environment Configuration](#environment-configuration)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### All Environments

- Python 3.12+
- PostgreSQL 16+ (local Docker or cloud-hosted)
- Git

### Development

- [uv package manager](https://docs.astral.sh/uv/)
- Docker and Docker Compose

### Production

- Docker (for containerized deployment)
- Cloud provider account (AWS, GCP, Azure, etc.)
- Database hosting (AWS RDS, Neon, Supabase, etc.)

## Development Deployment

### Automated Setup (Recommended)

Use the provided setup script:

```bash
chmod +x scripts/setup-dev.sh
./scripts/setup-dev.sh
```

This script will:
1. ✅ Check prerequisites (uv, Docker)
2. 📦 Install Python dependencies
3. 🌐 Install Playwright browsers (Chromium)
4. 🗄️ Start PostgreSQL via Docker Compose
5. 📝 Create `.env` file from template
6. 🗄️ Initialize database with Alembic migrations

### Manual Setup

If you prefer manual setup:

```bash
# 1. Install dependencies
uv sync

# 2. Install Playwright browsers (CRITICAL!)
uv run playwright install chromium

# 3. Start PostgreSQL
docker compose up -d

# 4. Configure environment
cp .env.example .env
# Edit .env with your settings

# 5. Initialize database
uv run winerank db init
```

### Verify Installation

```bash
# Check database connection
uv run python -c "from winerank.common.db import get_engine; print(get_engine().url)"

# Check Playwright
ls ~/.cache/ms-playwright/

# Run a test crawl
uv run winerank crawl --michelin 3
```

## Production Deployment

### Option 1: Docker Deployment

#### Build Docker Image

```bash
# Build the image
docker build -t winerank-agent:latest .

# Test locally
docker run --rm \
  -e WINERANK_DATABASE_URL="postgresql://user:pass@host:5432/db" \
  winerank-agent:latest \
  uv run winerank --help
```

#### Deploy to Cloud

**AWS ECS/Fargate:**

```bash
# Tag for ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin YOUR_ECR_URI

docker tag winerank-agent:latest YOUR_ECR_URI/winerank-agent:latest
docker push YOUR_ECR_URI/winerank-agent:latest

# Create ECS task definition with:
# - Environment variables from .env
# - Sufficient CPU/Memory for Playwright
# - Persistent volume for /app/data/downloads
```

**Google Cloud Run:**

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/winerank-agent
gcloud run deploy winerank-agent \
  --image gcr.io/PROJECT_ID/winerank-agent \
  --platform managed \
  --region us-central1 \
  --set-env-vars "WINERANK_DATABASE_URL=postgresql://..." \
  --memory 2Gi \
  --cpu 2
```

### Option 2: VM Deployment

For a traditional VM (EC2, Compute Engine, etc.):

```bash
# SSH into VM
ssh user@your-vm

# Clone repository
git clone YOUR_REPO_URL
cd winerank-agent

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# CRITICAL: Install Playwright browsers
uv run playwright install chromium
uv run playwright install-deps  # Install system dependencies

# Configure environment
cp .env.example .env
# Edit .env with production database URL

# Initialize database (one-time)
uv run winerank db init

# Run crawler
uv run winerank crawl --michelin 3
```

#### Systemd Service (Optional)

Create `/etc/systemd/system/winerank-crawler.service`:

```ini
[Unit]
Description=Winerank Crawler Service
After=network.target

[Service]
Type=simple
User=winerank
WorkingDirectory=/opt/winerank-agent
Environment="PATH=/home/winerank/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/winerank/.local/bin/uv run winerank crawl --michelin all
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable winerank-crawler
sudo systemctl start winerank-crawler
sudo systemctl status winerank-crawler
```

### Database Setup

#### Managed PostgreSQL

**AWS RDS:**
- Create PostgreSQL 16 instance
- Configure security groups for access
- Use connection string in `.env`

**Neon (Serverless):**
```bash
# Get connection string from Neon dashboard
WINERANK_DATABASE_URL=postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/winerank
```

**Supabase:**
```bash
# Use direct connection (not pooler) for migrations
WINERANK_DATABASE_URL=postgresql://postgres:pass@db.xxx.supabase.co:5432/postgres
```

#### Initialize Production Database

```bash
# Run migrations
uv run winerank db init

# Verify
uv run winerank crawl-status
```

## Environment Configuration

### Required Environment Variables

```bash
# Database (REQUIRED)
WINERANK_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname

# Crawler Settings
WINERANK_MICHELIN_LEVEL=3                    # 3, 2, 1, gourmand, selected, all
WINERANK_RESTAURANT_WEBSITE_DEPTH=4          # Max link depth
WINERANK_MAX_RESTAURANT_PAGES=20             # Max pages per restaurant
WINERANK_CRAWLER_CONCURRENCY=3               # Parallel crawls

# Playwright
WINERANK_HEADLESS=true                       # Must be true in production
WINERANK_BROWSER_TIMEOUT=30000               # 30 seconds
```

### Production Best Practices

1. **Headless Mode**: Always set `WINERANK_HEADLESS=true` in production
2. **Resource Limits**: Playwright requires ~2GB RAM per browser instance
3. **Concurrency**: Start with `WINERANK_CRAWLER_CONCURRENCY=3` and adjust based on resources
4. **Storage**: Ensure sufficient disk space for `/app/data/downloads`
5. **Secrets**: Use secret managers (AWS Secrets Manager, GCP Secret Manager) for sensitive data

## Troubleshooting

### "Executable doesn't exist" - Playwright Browsers Not Installed

**Error:**
```
BrowserType.launch: Executable doesn't exist at .../chromium-1208/chrome-headless-shell
```

**Solution:**
```bash
# Development
uv run playwright install chromium

# Production (Docker)
# Already included in Dockerfile via:
# RUN uv run playwright install chromium

# Production (VM)
uv run playwright install chromium
uv run playwright install-deps  # Install system dependencies
```

### "Invalid connection type" - Database Connection Error

**Error:**
```
Invalid connection type: <class 'sqlalchemy.engine.base.Engine'>
```

**Solution:**
Ensure `WINERANK_DATABASE_URL` uses correct format:
```bash
# Correct
postgresql+psycopg://user:pass@host:5432/db

# Incorrect
postgresql://user:pass@host:5432/db  # Missing +psycopg
```

### Database Connection Timeout

**Solution:**
- Check firewall rules allow connection from application server
- Verify database is running: `docker compose ps` (dev) or cloud console (prod)
- Test connection: `psql $WINERANK_DATABASE_URL`

### Playwright System Dependencies Missing (Linux)

**Error:**
```
Error: Host system is missing dependencies
```

**Solution:**
```bash
# Ubuntu/Debian
uv run playwright install-deps chromium

# Or manually install
sudo apt-get update && sudo apt-get install -y \
  libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
  libxdamage1 libxfixes3 libxrandr2 libgbm1 \
  libasound2 libpango-1.0-0
```

### Out of Memory During Crawl

**Solution:**
- Reduce `WINERANK_CRAWLER_CONCURRENCY`
- Increase instance memory (2GB minimum per browser)
- Enable swap if running on small VM

## Monitoring

### Job Status

```bash
# Check recent jobs
uv run winerank crawl-status

# Monitor database
uv run winerank db-manager  # Streamlit UI at http://localhost:8501
```

### Logs

```bash
# Docker
docker compose logs -f postgres

# Systemd service
sudo journalctl -u winerank-crawler -f

# Application logs (if enabled)
tail -f logs/winerank.log
```

## Scaling Considerations

### Horizontal Scaling

- Run multiple crawler instances with different Michelin levels
- Use job queue (Celery, RQ) for distributed processing
- Implement rate limiting to respect website policies

### Vertical Scaling

- Each Playwright browser requires ~500MB-1GB RAM
- CPU: 2+ cores recommended for concurrent crawls
- Disk: Plan for ~10-50MB per wine list PDF

## Security

1. **Database**: Use SSL connections in production
2. **Secrets**: Never commit `.env` file, use secret managers
3. **Network**: Restrict database access to application servers only
4. **Updates**: Keep Playwright and dependencies updated for security patches

## Support

For issues not covered here:
1. Check [GitHub Issues](YOUR_REPO_URL/issues)
2. Review application logs
3. Verify environment variables
4. Test with minimal configuration first
