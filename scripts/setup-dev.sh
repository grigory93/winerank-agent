#!/bin/bash
# Development environment setup script for Winerank Agent

set -e  # Exit on error

echo "🍷 Setting up Winerank Agent Development Environment..."

# Check prerequisites
echo "Checking prerequisites..."
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is not installed. Install from: https://docs.astral.sh/uv/"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed. Install from: https://www.docker.com/"
    exit 1
fi

echo "✅ Prerequisites met"

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
uv sync

# Install Playwright browsers
echo ""
echo "🌐 Installing Playwright browsers..."
uv run playwright install chromium

# Start PostgreSQL
echo ""
echo "🗄️  Starting PostgreSQL..."
docker compose up -d

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be healthy..."
timeout=30
counter=0
until docker compose ps postgres | grep -q "healthy" || [ $counter -eq $timeout ]; do
    sleep 1
    ((counter++))
    if [ $counter -eq $timeout ]; then
        echo "❌ Error: PostgreSQL failed to start within ${timeout} seconds"
        docker compose logs postgres
        exit 1
    fi
done

echo "✅ PostgreSQL is ready"

# Setup environment file
if [ ! -f .env ]; then
    echo ""
    echo "📝 Creating .env file..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env from .env.example"
        echo "⚠️  Please edit .env and configure your settings"
    else
        echo "⚠️  Warning: .env.example not found, skipping .env creation"
    fi
else
    echo ""
    echo "📝 Found existing .env file, using it"
fi

# Initialize database
echo ""
echo "🗄️  Initializing database..."
uv run winerank db init

echo ""
echo "✅ Development environment setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env if needed"
echo "  2. Run crawler: uv run winerank crawl"
echo "  3. Launch DB Manager: uv run winerank db-manager"
