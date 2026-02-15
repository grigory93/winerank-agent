# Winerank Scripts

Utility scripts for managing the Winerank Agent.

## Available Scripts

### `setup-dev.sh`

Automated development environment setup script.

**Usage:**
```bash
chmod +x scripts/setup-dev.sh
./scripts/setup-dev.sh
```

**What it does:**
1. ✅ Verifies prerequisites (uv, Docker)
2. 📦 Installs Python dependencies via `uv sync`
3. 🌐 Installs Playwright browsers (Chromium)
4. 🗄️ Starts PostgreSQL via Docker Compose
5. 📝 Creates `.env` file from `.env.example` if needed
6. 🗄️ Initializes database with Alembic migrations

**Requirements:**
- uv package manager
- Docker and Docker Compose
- Git

**Environment:**
- Creates/uses `.env` file for configuration
- Starts PostgreSQL on `localhost:5432`

## Creating New Scripts

When adding new scripts to this directory:

1. **Use bash**: Start with `#!/bin/bash`
2. **Set exit on error**: Add `set -e` at the top
3. **Document**: Add description to this README
4. **Make executable**: `chmod +x scripts/your-script.sh`
5. **Test thoroughly**: Test in clean environment before committing

## Examples

### Run development setup
```bash
./scripts/setup-dev.sh
```

### Check what the script will do (dry run)
```bash
bash -x scripts/setup-dev.sh
```
