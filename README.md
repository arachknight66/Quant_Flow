# QuantFlow Quantitative Finance Platform

QuantFlow is a production-grade algorithmic trading and quantitative research platform. It integrates a high-performance FastAPI backend, a walk-forward validation machine learning pipeline using XGBoost and GARCH, and a real-time Next.js analytics frontend dashboard.

---

## Technical Stack
- **Backend**: FastAPI, SQLAlchemy 2.0 (Async), Alembic, Pydantic v2
- **Data & Caching**: PostgreSQL, Redis, `asyncpg`, `redis-py`
- **Machine Learning**: XGBoost, ARCH/GARCH (via `arch` library), Walk-Forward Validation
- **Frontend**: Next.js 14, TailwindCSS (optional / custom styling)
- **Deployment**: Docker, Docker Compose, Nginx

---

## Core System Architecture

### 1. Market Data Pipeline
- Fetches real-time and historical price bars from Yahoo Finance and Alpha Vantage.
- Implements two-tier caching:
  - **Memory Cache**: Local execution cache.
  - **Redis Cache**: Formatted as `ohlcv:{SYMBOL}:{interval}:{date_hash}` with automatic invalidation scanning patterns to prevent cross-symbol pollution.

### 2. Walk-Forward Validation ML Engine
- Strict sequential time-series walk-forward validation (never k-fold to avoid lookahead bias).
- Features calculated: RSI, MACD, Bollinger Bands, ATR.
- **Volatility Forecasting**: Real-time GARCH(1,1) model for predicting multi-step ahead conditional volatility paths.
- **Risk Metrics**: 95% Parametric and Historical Value-at-Risk (VaR), Conditional VaR (CVaR).
- **Position Sizing**: Quarter-Kelly (25%) sizing rule based on win probability, risk tolerance, and stop-loss boundaries.
- **Deployment Criteria**: Models are automatically deployed only if their out-of-sample Walk-Forward AUC is at least **0.53** (below 0.52 is treated as noise).

### 3. Real-Time Price Streaming
- Secured WebSocket interface at `/ws/prices` broadcasting price updates.
- Authenticated via JWT access tokens passed as query parameters (`/ws/prices?token=...`).

---

## Local Setup

### Prerequisites
- Python 3.11
- Poetry (Package manager)
- Docker & Docker Compose

### 1. Install Dependencies
```bash
poetry install
```

### 2. Configure Environment Variables
Create a `.env` file in the root directory:
```env
SECRET_KEY=your-highly-secure-at-least-32-char-random-string
POSTGRES_USER=postgres
POSTGRES_PASSWORD=yourpassword
POSTGRES_DB=quantplatform
REDIS_HOST=localhost
REDIS_PORT=6379
DEBUG=True
```

### 3. Run Database Migrations
```bash
poetry run alembic upgrade head
```

### 4. Seed Default Assets
Populate default symbols (AAPL, MSFT, TSLA, SPY, BTC-USD, ETH-USD):
```bash
poetry run python scripts/seed_assets.py
```

### 5. Start the Application
Run the FastAPI development server:
```bash
poetry run uvicorn backend.main:app --reload
```

---

## Running the Test Suite
QuantFlow includes a comprehensive, isolated suite of 40+ unit and integration tests covering backend APIs, ML features, and risk calculations.

Run all tests with code coverage:
```bash
poetry run pytest tests/ --cov=backend --cov=ml -vv
```

---

## Production Security Policies
- **Token Security**: Access tokens are kept in-memory; refresh tokens are stored in `httpOnly`, `SameSite=Strict`, `Secure` (based on `DEBUG` configuration) cookies.
- **Rate Limiting**: Critical endpoints (e.g., `/api/v1/analysis/analyze`) are protected via SlowAPI rate limiters (60 requests/minute).
- **Entropy Enforcement**: Startup checks enforce a strong `SECRET_KEY` (minimum 32 characters, no trivial words) to prevent misconfiguration in production environments.