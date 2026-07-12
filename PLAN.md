# QuantPlatform — Development Plan

**Status as of Phase 2.5:** Backend complete, ML pipeline verified, frontend rendering,
98 files, 66 Python, 21 TypeScript/TSX, 23/23 quick_verify checks passing.

This document covers everything that remains before the platform is production-ready.
Phases are ordered by dependency — each phase unlocks the next.

---

## What is already done

| Phase | What was built | Verified |
|---|---|---|
| 2.0 | Missing files, 28 `__init__.py`, Alembic, Signal ORM, WalkForwardSplitter canonical location | 13/13 |
| 2.1 | `fillna` deprecation, `group_by` removal, `price_polling_task` wired, `invalidate_cache` scoped SCAN | 6/6 |
| 2.2 | `COOKIE_SECURE` dynamic, HSTS header, HTTPS nginx block, `decode_token` simplified | 8/8 |
| 2.3 | Full repo assembled, 20/20 imports, feature pipeline, risk engine, backtester, auth | 65/65 |
| 2.4 | Training scripts, `quick_verify.py`, honest AUC reporting, `evaluate_model.py` | 23/23 |
| 2.5 | Next.js 14 frontend: Sidebar, Header, AnalysisPanel, SignalCard, charts, WebSocket hook | 23/23 |

---

## Phase 3.0 — Test Suite (blocking: cannot deploy without this)

**Why first:** The CI pipeline in Phase 3.6 requires tests. Every subsequent phase adds
behaviour that needs coverage. Writing tests now while the code is fresh is always
faster than writing them after.

**Target:** 80%+ line coverage on `backend/` and `ml/`. The two existing test files
cover backtesting and pipeline integration but nothing else.

### 3.0.1 — Auth tests
**File:** `tests/test_auth.py`
**Covers:** register duplicate email → 409, login wrong password → 401,
login success → access token + cookie, refresh → new tokens,
logout → cookie cleared, `/me` with valid/invalid token.
**Key assertion:** `COOKIE_SECURE` is `False` in test environment (DEBUG=True),
so cookies actually arrive in the test client.

### 3.0.2 — Market data tests
**File:** `tests/test_market.py`
**Covers:** `/ohlcv` with mocked yfinance, cache hit path (mock Redis),
cache miss → DB fetch → API fetch fallback, `invalidate_cache` only
deletes keys for the requested symbol (not all symbols).
**Key assertion:** `scan_iter` pattern `ohlcv:AAPL:*` does NOT match `ohlcv:MSFT:*`.

### 3.0.3 — Analysis endpoint tests
**File:** `tests/test_analysis.py`
**Covers:** `/analyze` with no model → HOLD + warning, `/analyze` with
synthetic model → BUY/SELL/HOLD, position sizing only when capital provided,
`/backtest` with no model → 422, insufficient bars → 422.

### 3.0.4 — Risk engine unit tests
**File:** `tests/test_risk_engine.py`
**Covers:** Kelly formula edge cases (zero loss, p=0, p=1), all three
risk profiles never exceed `max_position_pct`, historical VaR ≥ 0,
parametric VaR ≥ 0, max drawdown returns negative value.

### 3.0.5 — ML integrity tests (CI-critical)
**Files:** `tests/test_features.py`, `tests/test_walk_forward.py`
**Covers:** no-lookahead at bars 50/100/200/300, RSI ∈ [0,100],
ATR > 0, WalkForwardSplitter all train < all test across all split counts,
gap is respected, chronological fold order.
**Note:** These run in the `ml-integrity-test` CI job separately from
the main test suite because they are slow (~30s) and categorically different
from functional tests.

### 3.0.6 — Model monitor tests
**File:** `tests/test_model_monitor.py`
**Covers:** KS test fires for clearly different distributions,
PSI fires above threshold, accuracy drift fires when recent acc drops > 5pp,
no alerts on stable distributions.

### 3.0.7 — Monte Carlo tests
**File:** `tests/test_monte_carlo.py`
**Covers:** probabilities ∈ [0,1], CVaR ≥ VaR (always), percentiles ordered,
`prob_20pct_loss ≤ prob_10pct_loss` (monotonicity), result is reproducible
with same `random_seed`.

### 3.0.8 — GARCH tests
**File:** `tests/test_garch.py`
**Covers:** `alpha + beta < 1` (stationarity), `omega > 0`, `long_run_vol > 0`,
1-day forecast returns positive float, manual MLE path (no arch library)
gives similar results to arch path.

### 3.0.9 — Integration test
**File:** `tests/integration/test_api.py`
**Covers:** Full HTTP round-trip with `httpx.AsyncClient` + `AsyncSession`
against a real in-memory SQLite (or test Postgres). Register → login →
analyze → portfolio/signals/history. No mocks — tests the real stack.

**Acceptance criteria for Phase 3.0:**
- `pytest tests/ --cov=backend --cov=ml --cov-report=term-missing` reports ≥ 80% line coverage
- All tests pass in < 60 seconds (excluding integration tests)
- No test uses `time.sleep()` — all async

---

## Phase 3.1 — CI/CD Pipeline

**File:** `.github/workflows/ci.yml`

```yaml
jobs:
  backend-test:     pytest + coverage upload to Codecov
  frontend-test:    npm run type-check + lint + build
  ml-integrity:     test_features.py + test_walk_forward.py (no-lookahead CI gate)
  docker-build:     docker build both images, confirm they start
  deploy-staging:   Railway/Fly.io push on merge to develop
```

**File:** `.github/workflows/deploy.yml`
```yaml
on: push to main
jobs:
  deploy-production: Railway/Fly.io push + alembic upgrade head + healthcheck
```

**File:** `deployment/postgres/init.sql`
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
```
PostgreSQL needs `uuid-ossp` for `gen_random_uuid()` used in the migration.
Without this the first `alembic upgrade head` fails on a fresh DB.

**Acceptance criteria:**
- PR to `main` blocks merge if any CI job fails
- `ml-integrity-test` job is required — a PR that introduces lookahead cannot merge
- Staging deploy happens automatically on push to `develop`

---

## Phase 3.2 — Security Hardening (remaining gaps)

Six security issues remain after Phase 2.2. None are critical blockers for development
but all must be closed before accepting real user accounts.

### 3.2.1 — Rate limiting on `/analyze`
`/analyze` calls `build_feature_matrix` (CPU-bound, ~200ms) and potentially
`yfinance` (network). Without rate limiting, a single client can saturate the
backend. Add `slowapi` (FastAPI-native `limits` integration):

```python
# backend/middleware/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# In analysis router:
@router.post("/analyze")
@limiter.limit("10/minute")
async def analyze_asset(...):
```

The nginx `limit_req_zone` already rate-limits at the proxy layer but that
only protects against external callers — internal service calls bypass it.

### 3.2.2 — WebSocket authentication
`/ws/prices` currently accepts any connection with no auth check. A user
could subscribe to unlimited symbols and create high-frequency polling load.
Fix: require a valid JWT query parameter on connect:

```python
@router.websocket("/prices")
async def price_stream(websocket: WebSocket, token: str = Query(...)):
    payload = auth_service.decode_token(token)   # raises on invalid
    ...
```

### 3.2.3 — JWT revocation (jti blacklist)
The `jti` (JWT ID) claim is already generated in `create_access_token` but
never stored or checked. On logout, the `jti` should be written to Redis
with the token's remaining TTL. On each request, `get_current_user` should
check the blacklist before trusting the token.

```python
# In auth_service.py decode_token():
jti = payload.get("jti")
if jti and await redis.get(f"revoked:{jti}"):
    raise HTTPException(401, "Token revoked")

# In auth router logout():
await redis.setex(f"revoked:{jti}", ttl_remaining, "1")
```

### 3.2.4 — Symbol input sanitisation
The `symbol` field accepts any string up to some pydantic length limit but
is passed directly to yfinance and used in Redis cache keys. Add an explicit
allowlist validator:

```python
@field_validator("symbol")
@classmethod
def validate_symbol(cls, v: str) -> str:
    import re
    if not re.match(r'^[A-Z0-9\-\.]{1,10}$', v.upper()):
        raise ValueError("Invalid symbol format")
    return v.upper()
```

### 3.2.5 — SECRET_KEY entropy check
Add a startup validator that rejects weak keys:

```python
# In config.py model_validator:
if len(self.SECRET_KEY) < 32:
    raise ValueError("SECRET_KEY must be at least 32 characters")
if self.SECRET_KEY == "replace-this-with-a-real-secret-key-at-least-32-chars":
    raise ValueError("Change the default SECRET_KEY before running")
```

### 3.2.6 — CSRF token for state-changing requests
The httpOnly SameSite=Strict cookie provides good CSRF protection for
same-origin requests, but add a `X-Requested-With: XMLHttpRequest` header
check as a defense-in-depth layer. FastAPI middleware, 5 lines.

---

## Phase 3.3 — Portfolio & Positions (stub → real)

`backend/api/routers/portfolio.py::get_positions()` currently returns `[]`.
This is the largest functional gap between "it looks like a trading platform"
and "it is a trading platform".

### 3.3.1 — Database migration: portfolio_positions table

```sql
-- alembic/versions/002_portfolio_positions.py
CREATE TABLE portfolio_positions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    asset_id    UUID REFERENCES assets(id),
    quantity    FLOAT NOT NULL,
    avg_entry_price FLOAT NOT NULL,
    open_date   TIMESTAMPTZ NOT NULL DEFAULT now(),
    close_date  TIMESTAMPTZ,
    is_open     BOOLEAN DEFAULT true,
    stop_loss   FLOAT,
    take_profit FLOAT,
    signal_id   UUID REFERENCES signals(id),
    notes       TEXT
);
CREATE INDEX ix_positions_user_open ON portfolio_positions (user_id, is_open);
```

### 3.3.2 — Signal persistence
The `/analyze` endpoint currently generates a signal but never saves it to the DB.
Add a `save_signal()` helper that writes to the `signals` table. The signal's
`features_snapshot` (already in the schema) enables retrospective debugging of
why a model made a particular call.

### 3.3.3 — Paper trading: open/close positions
Two new endpoints:

```
POST /api/v1/portfolio/positions/open
  body: { signal_id, quantity, entry_price }
  → creates a portfolio_position row

POST /api/v1/portfolio/positions/{id}/close
  body: { exit_price, exit_reason }
  → sets close_date, is_open=false, records P&L
```

### 3.3.4 — Real portfolio summary
`get_portfolio_summary()` currently returns `capital_usd` as `total_value_usd`
and zeroes for everything else. With positions in DB:

```python
open_positions = await db.execute(
    select(PortfolioPosition)
    .where(PortfolioPosition.user_id == user.id, PortfolioPosition.is_open == True)
)
# for each: fetch current price → compute unrealised P&L
invested_usd = sum(p.quantity * p.avg_entry_price for p in positions)
current_value = sum(p.quantity * current_prices[p.asset.symbol] for p in positions)
```

### 3.3.5 — Frontend: Portfolio page
New route `apps/web/src/app/portfolio/page.tsx`:
- Open positions table (symbol, qty, entry, current, P&L, P&L%)
- Closed positions history with realized P&L
- Signal history from `/portfolio/signals/history`
- Portfolio allocation pie chart (recharts)

---

## Phase 3.4 — Advanced ML (Phase 3 features)

The directories `ml/models/deep/` and `ml/models/ensemble/` exist but are empty.
The GARCH and HMM models are written but not connected to the training pipeline.

### 3.4.1 — GARCH features integration
Add GARCH conditional volatility as an XGBoost input feature in `build_feature_matrix`:

```python
# In ml/features/technical_indicators.py, build_feature_matrix():
from ml.models.volatility.garch_model import GARCHVolatilityModel
garch = GARCHVolatilityModel()
log_returns = np.log(close / close.shift(1)).dropna()
try:
    garch.fit(log_returns)
    features["garch_vol_1d"] = garch.forecast_1day_vol(log_returns)
    features["garch_persistence"] = garch.params.persistence
except Exception:
    pass  # degrade gracefully if optimizer fails
```

Expected AUC uplift: +0.01 to +0.03 (volatility clustering is one of the
most reliable features in financial ML).

### 3.4.2 — HMM regime features integration
Similarly, add regime labels as XGBoost features:

```python
from ml.models.regime.hmm_regime_detector import HMMRegimeDetector
detector = HMMRegimeDetector(n_regimes=3)
detector.fit(log_returns)
features = detector.add_regime_features(features, log_returns)
# Adds: regime_bull, regime_bear, regime_sideways, regime_entropy
```

This conditions the model on market state — a BUY signal in a bull regime
should carry more weight than the same signal in a bear regime.

### 3.4.3 — Optuna hyperparameter tuning
`optuna` is declared in `pyproject.toml` but never used. Add an optional
`--tune` flag to `train_model.py`:

```python
def tune_hyperparameters(X_train, y_train, n_trials=50) -> dict:
    import optuna
    def objective(trial):
        params = {
            "max_depth":       trial.suggest_int("max_depth", 3, 6),
            "learning_rate":   trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "subsample":       trial.suggest_float("subsample", 0.6, 1.0),
            "n_estimators":    trial.suggest_int("n_estimators", 100, 500),
            "min_child_weight":trial.suggest_int("min_child_weight", 5, 50),
        }
        model = XGBoostSignalModel(**params)
        wf = model.walk_forward_evaluate(X_train, y_train, n_splits=3)
        return wf["mean_auc"]
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)
    return study.best_params
```

### 3.4.4 — Ensemble stacker
`ml/models/ensemble/` is empty. Add a stacking ensemble that combines:
- XGBoost signal probability
- GARCH 1-day vol forecast (as a position size scaler)
- HMM regime multiplier (from `predict_current_regime()`)

```python
# ml/models/ensemble/signal_stacker.py
class SignalStacker:
    def predict(self, features, close) -> dict:
        xgb_signal   = self.xgb_model.predict(features)
        garch_vol    = self.garch_model.forecast_1day_vol(close.pct_change().dropna())
        regime       = self.hmm_detector.predict_current_regime(close.pct_change().dropna())

        # Scale probability by regime conviction
        regime_mult  = regime["position_size_multiplier"]  # 1.0/0.6/0.3
        # Reduce confidence in high-vol regime
        vol_scale    = min(1.0, 0.20 / max(garch_vol / np.sqrt(252), 0.01))

        blended_prob = xgb_signal["prob_profit"] * regime_mult * vol_scale
        return {**xgb_signal, "prob_profit": blended_prob,
                "regime": regime["current_regime"], "garch_vol_daily": garch_vol}
```

### 3.4.5 — Scheduled model retraining
Add a background task that checks if any model is >30 days old and has
sufficient new data, then retrains:

```python
# backend/services/model_retraining_service.py
async def check_and_retrain_stale_models():
    for symbol in TRACKED_SYMBOLS:
        result = await ml_service.train_model_for_symbol(
            symbol, "1d", ohlcv_df, force_retrain=False
        )
        if result["status"] == "trained":
            log.info("Model retrained", symbol=symbol, **result)
```

Schedule in `main.py` lifespan alongside `price_polling_task`, run weekly.

---

## Phase 3.5 — Data Pipeline Expansion

### 3.5.1 — Binance collector
`BINANCE_API_KEY` is in `.env.example` but there is no `BinanceCollector`.
Add `data_pipeline/collectors/binance_collector.py` using `python-binance`.
This gives millisecond-resolution crypto OHLCV vs yfinance's minute delay.

### 3.5.2 — Alpha Vantage collector
`ALPHA_VANTAGE_API_KEY` is declared but unused. Add `AlphaVantageCollector`
for fundamental data (EPS, P/E, earnings dates) that yfinance sometimes
misses for international stocks.

### 3.5.3 — Asset seeding script
**File:** `scripts/seed_assets.py`
Populate the `assets` table with a standard watchlist on first deploy:

```python
SEED_SYMBOLS = [
    ("AAPL", "Apple Inc.", "stock"),  ("MSFT", "Microsoft", "stock"),
    ("NVDA", "NVIDIA", "stock"),      ("TSLA", "Tesla", "stock"),
    ("BTC-USD", "Bitcoin", "crypto"), ("ETH-USD", "Ethereum", "crypto"),
    ("SPY", "S&P 500 ETF", "etf"),    ("QQQ", "Nasdaq ETF", "etf"),
    # ... 50+ more
]
```

Without this, the `/market/search` endpoint returns nothing until symbols
are auto-created via their first OHLCV fetch.

### 3.5.4 — OHLCV backfill script
**File:** `scripts/backfill_ohlcv.py`
Download 5 years of daily data for every seeded symbol:

```bash
python scripts/backfill_ohlcv.py --symbols AAPL,MSFT,NVDA --years 5 --interval 1d
```

Without a warm DB, the first user request for AAPL data causes a 2–3 second
yfinance network call. After backfill, it's a 10ms DB query.

---

## Phase 3.6 — README and Developer Experience

The `README.md` contains only `# Quant_Flow`. This is the single highest-leverage
documentation change — it's the first thing any developer sees.

### README structure
```markdown
# QuantPlatform
AI-powered quantitative finance analysis platform.

## Architecture
[diagram showing: Next.js → FastAPI → PostgreSQL/Redis → yfinance]

## Quickstart (5 minutes)
cp .env.example .env    # generate SECRET_KEY
docker-compose up -d
alembic upgrade head
uvicorn backend.main:app --reload
cd apps/web && npm run dev

## Running tests
python scripts/quick_verify.py    # 23/23 no-network check
pytest tests/ --cov=backend

## Training your first model
python scripts/train_model.py --symbol AAPL --years 5

## Honest expectations
[the AUC table from train_model.py docstring]

## Project structure
[tree of all 98 files with one-line descriptions]
```

---

## Phase 4.0 — Production Readiness

These items have no code gaps — they are operational concerns that block
a real deployment but don't require new feature code.

### 4.0.1 — Observability
- Structured logs (structlog is already configured) → ship to Datadog/Grafana Loki
- `backend/monitoring/model_monitor.py` is written → wire it to a `/monitoring/drift` endpoint
- Add Prometheus metrics endpoint (`/metrics`) via `prometheus-fastapi-instrumentator`
- Alert on: model drift, p95 latency > 500ms, error rate > 1%, Redis down

### 4.0.2 — Database performance
- Add `EXPLAIN ANALYZE` benchmarks for the top 5 query patterns
- The `ohlcv_data` table will hit 10M+ rows quickly for minute data — add a
  TimescaleDB hypertable or at minimum a partial index on `ts DESC WHERE interval='1d'`
- Connection pool sizing: `pool_size=10, max_overflow=20` may be too small
  under load — benchmark with `locust` before going live

### 4.0.3 — Secrets management
Move from `.env` file to a proper secrets backend:
- **Development:** `.env` file (current, fine)
- **Staging/Production:** AWS Secrets Manager, GCP Secret Manager, or Railway secrets
- Rotate `SECRET_KEY` procedure: deploy with both old and new key accepted during
  transition window, then cut over

### 4.0.4 — TLS certificates
`nginx.conf` references `/etc/letsencrypt/live/yourplatform.com/fullchain.pem`.
Add a `certbot` setup script:
```bash
# deployment/scripts/setup_tls.sh
certbot certonly --nginx -d yourplatform.com -d www.yourplatform.com
# Add cron: 0 0 * * * certbot renew --quiet
```

### 4.0.5 — Backup strategy
- PostgreSQL: `pg_dump` nightly to S3, retain 30 days
- ML artifacts: `ml/artifacts/` volume → S3 sync after each training run
- Redis: Redis persistence (`appendonly yes`) already in docker-compose

---

## Phase 5.0 — Mobile App Completion

The mobile scaffolding (`AnalysisScreen.tsx`, `push_notifications.ts`,
`app.config.ts`) exists but the app is not runnable yet.

### 5.0.1 — Expo project bootstrap
```bash
cd apps/mobile
npx create-expo-app . --template blank-typescript  # generates app.json, package.json
npm install @tanstack/react-query zustand expo-notifications expo-device
```

### 5.0.2 — Missing screens
- `src/screens/PortfolioScreen.tsx` — mirrors web portfolio page
- `src/screens/WatchlistScreen.tsx` — saved symbols with live prices
- `src/screens/SettingsScreen.tsx`  — risk tolerance, capital, push notification prefs

### 5.0.3 — Navigation
- `src/navigation/AppNavigator.tsx` using `@react-navigation/native`
- Bottom tab bar: Analysis | Portfolio | Watchlist | Settings

### 5.0.4 — Push notification backend endpoint
`notification_service.py` is written, but there is no endpoint to register
a device token. Add:
```
POST /api/v1/notifications/register-token
  body: { expo_push_token: str, platform: "ios"|"android" }
```
And a `device_tokens` table to store them per user.

### 5.0.5 — EAS Build pipeline
```json
// eas.json
{
  "build": {
    "production": { "android": { "buildType": "apk" }, "ios": { "simulator": false } }
  }
}
```

---

## Summary: Ordered Work Queue

Priority is by blocking dependency, then by user-facing impact.

### Must-do before any real users (P0)

| # | Task | Phase | Effort |
|---|---|---|---|
| 1 | Test suite (80% coverage) | 3.0 | 2 days |
| 2 | CI pipeline + ml-integrity gate | 3.1 | 4 hours |
| 3 | PostgreSQL init.sql (uuid-ossp) | 3.1 | 15 min |
| 4 | Rate limiting on /analyze | 3.2.1 | 1 hour |
| 5 | WebSocket authentication | 3.2.2 | 1 hour |
| 6 | Symbol input validation | 3.2.4 | 30 min |
| 7 | SECRET_KEY entropy check | 3.2.5 | 30 min |
| 8 | Asset seeding script | 3.5.3 | 2 hours |
| 9 | README | 3.6 | 2 hours |

### High value, not blocking (P1)

| # | Task | Phase | Effort |
|---|---|---|---|
| 10 | GARCH + HMM as features (AUC uplift) | 3.4.1–3.4.2 | 1 day |
| 11 | Optuna tuning | 3.4.3 | 4 hours |
| 12 | Portfolio positions table + signal persistence | 3.3.1–3.3.2 | 1 day |
| 13 | Paper trading open/close endpoints | 3.3.3 | 4 hours |
| 14 | Portfolio frontend page | 3.3.5 | 1 day |
| 15 | JWT revocation blacklist | 3.2.3 | 3 hours |
| 16 | OHLCV backfill script | 3.5.4 | 2 hours |

### ML Phase 3 (P2, after first real AUC confirmed)

| # | Task | Phase | Effort |
|---|---|---|---|
| 17 | Ensemble stacker | 3.4.4 | 2 days |
| 18 | Scheduled retraining | 3.4.5 | 4 hours |
| 19 | Binance collector | 3.5.1 | 1 day |
| 20 | Alpha Vantage collector | 3.5.2 | 4 hours |

### Production operations (P3, before launch)

| # | Task | Phase | Effort |
|---|---|---|---|
| 21 | Prometheus metrics + Grafana dashboard | 4.0.1 | 4 hours |
| 22 | Model drift endpoint (/monitoring/drift) | 4.0.1 | 2 hours |
| 23 | TimescaleDB or partial index for ohlcv_data | 4.0.2 | 4 hours |
| 24 | TLS cert setup script | 4.0.4 | 1 hour |
| 25 | Nightly PostgreSQL backup to S3 | 4.0.5 | 2 hours |

### Mobile (P4, parallel track)

| # | Task | Phase | Effort |
|---|---|---|---|
| 26 | Expo bootstrap + navigation | 5.0.1–5.0.3 | 1 day |
| 27 | Missing screens (Portfolio, Watchlist, Settings) | 5.0.2 | 2 days |
| 28 | Device token endpoint + DB table | 5.0.4 | 3 hours |
| 29 | EAS build pipeline | 5.0.5 | 2 hours |

---

## Effort summary

| Priority | Items | Total effort |
|---|---|---|
| P0 — Blocking | 9 items | ~2.5 days |
| P1 — High value | 7 items | ~5 days |
| P2 — ML Phase 3 | 4 items | ~4 days |
| P3 — Production ops | 5 items | ~1.5 days |
| P4 — Mobile | 4 items | ~3 days |
| **Total** | **29 items** | **~16 days** |

---

## Known honest limitations (document these, don't hide them)

1. **AUC is the only honest metric.** In-sample accuracy, confusion matrices,
   and fixed-date backtests are all forms of data snooping on financial data.
   Every model evaluation must use walk-forward out-of-sample AUC.

2. **Most first models will have AUC < 0.53.** This is not a bug. Random-walk
   price data has no learnable patterns in a 5-year daily sample. The correct
   response is to add economically-motivated features (GARCH, HMM regime,
   earnings calendar, short interest) — not to lower the threshold.

3. **Backtest results are optimistic.** The backtest engine correctly models
   slippage and commission but does NOT model: market impact of large orders,
   short selling costs, margin requirements, execution latency, or adverse
   selection. Real live performance will be worse.

4. **yfinance data quality varies.** For production, supplement or replace with
   Polygon.io (paid, institutional grade) or Alpaca Market Data (free tier with
   15-min delay). The `BaseCollector` abstraction makes swapping trivial.

5. **This is not financial advice.** Every signal response includes this warning.
   The platform is a research and education tool.
