#!/bin/bash
# scripts/scaffold.sh
# Run this once to create the full monorepo structure

set -e

echo "🏗️  Scaffolding QuantPlatform monorepo..."

# Root
mkdir -p quant-platform && cd quant-platform

# Backend
mkdir -p backend/{api/routers,core,models,services,monitoring}
mkdir -p ml/{models/{xgboost,lstm,regime,ensemble,volatility},features,training,backtesting,risk,inference}
mkdir -p data_pipeline/{collectors,transformers,validators}
mkdir -p shared/{schemas,types,constants,utils}

# Frontend
mkdir -p apps/web/src/{app,components/{analysis,charts,portfolio,auth,ui},hooks,lib,store,types}
mkdir -p apps/mobile/src/{screens,components,hooks,lib,store,notifications}

# Config
mkdir -p deployment/{nginx,postgres} .github/workflows ml/artifacts tests/{backend,ml,integration}
mkdir -p alembic/versions docs scripts

# Root files
cat > .env.example << 'EOF'
# Application
SECRET_KEY=your-very-secret-key-change-this-in-production
DEBUG=false

# Database
POSTGRES_SERVER=localhost
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme
POSTGRES_DB=quantplatform
POSTGRES_PORT=5432

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# External APIs
ALPHA_VANTAGE_API_KEY=
BINANCE_API_KEY=
BINANCE_SECRET_KEY=

# ML
MODEL_ARTIFACTS_DIR=./ml/artifacts

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws

# Mobile
EXPO_PUBLIC_API_URL=http://localhost:8000/api/v1
EXPO_PUBLIC_WS_URL=ws://localhost:8000/ws
EOF

cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/
.mypy_cache/
.ruff_cache/
dist/
build/

# Environment
.env
.env.local
.env.*.local

# ML artifacts (large files)
ml/artifacts/**/*.joblib
ml/artifacts/**/*.pt
ml/artifacts/**/*.pkl

# Node
node_modules/
.next/
.expo/

# Database
*.db
*.sqlite

# Logs
*.log
logs/

# Docker
.docker/

# Coverage
htmlcov/
.coverage
coverage.xml
EOF

# __init__.py files
find backend ml data_pipeline shared -type d | while read dir; do
    touch "$dir/__init__.py"
done

echo "✅ Scaffold complete."
echo ""
echo "Next steps:"
echo "  1. cp .env.example .env && vim .env  # Set your secrets"
echo "  2. pip install poetry && poetry install"
echo "  3. docker-compose up -d postgres redis"
echo "  4. poetry run alembic upgrade head"
echo "  5. poetry run uvicorn backend.main:app --reload"
echo "  6. cd apps/web && npm install && npm run dev"