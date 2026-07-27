import ast
from pathlib import Path
import subprocess
import sys

def file_exists(p):
    return Path(p).exists()

def exec_body(filepath, funcname):
    if not Path(filepath).exists():
        return ""
    try:
        tree = ast.parse(Path(filepath).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == funcname:
                body = n.body
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    body = body[1:]  # strip docstring
                return ast.unparse(ast.Module(body=body, type_ignores=[]))
    except Exception:
        pass
    return ""

def run_quick_verify():
    p = Path("scripts/quick_verify.py")
    if p.exists():
        res = subprocess.run([sys.executable, str(p)], capture_output=True, text=True)
        return res.returncode == 0
    return True

checks = {
    # P0
    ".github/workflows/ci.yml":        file_exists(".github/workflows/ci.yml"),
    "deployment/postgres/init.sql":    file_exists("deployment/postgres/init.sql"),
    "rate limiting in main.py":        "limiter" in Path("backend/main.py").read_text(encoding="utf-8") if file_exists("backend/main.py") else False,
    "ws token auth":                   "token" in exec_body("backend/api/routers/ws.py", "price_stream"),
    "symbol validator":                "field_validator" in Path("backend/api/routers/analysis.py").read_text(encoding="utf-8") if file_exists("backend/api/routers/analysis.py") else False,
    "SECRET_KEY entropy check":        "len(self.SECRET_KEY) < 32" in Path("backend/core/config.py").read_text(encoding="utf-8") if file_exists("backend/core/config.py") else False,
    "seed_assets.py":                  file_exists("scripts/seed_assets.py"),
    "README > 200 lines":              len(Path("README.md").read_text(encoding="utf-8").splitlines()) > 200 if file_exists("README.md") else False,
    # P1
    "GARCH in features":               "GARCHVolatilityModel" in Path("ml/features/technical_indicators.py").read_text(encoding="utf-8") if file_exists("ml/features/technical_indicators.py") else False,
    "HMM in features":                 "HMMRegimeDetector" in Path("ml/features/technical_indicators.py").read_text(encoding="utf-8") if file_exists("ml/features/technical_indicators.py") else False,
    "optuna in train_model.py":        "optuna" in Path("scripts/train_model.py").read_text(encoding="utf-8") if file_exists("scripts/train_model.py") else False,
    "002_portfolio_positions.py":      file_exists("alembic/versions/002_portfolio_positions.py"),
    "position.py ORM":                 file_exists("backend/models/position.py"),
    "signal persisted in /analyze":    "Signal(" in Path("backend/api/routers/analysis.py").read_text(encoding="utf-8") if file_exists("backend/api/routers/analysis.py") else False,
    "positions/open endpoint":         "entry_price" in Path("backend/api/routers/portfolio.py").read_text(encoding="utf-8") if file_exists("backend/api/routers/portfolio.py") else False,
    "positions/close endpoint":        "exit_price" in Path("backend/api/routers/portfolio.py").read_text(encoding="utf-8") if file_exists("backend/api/routers/portfolio.py") else False,
    "get_positions not stub":          "return []" not in exec_body("backend/api/routers/portfolio.py", "get_positions"),
    "portfolio/page.tsx":              file_exists("apps/web/src/app/portfolio/page.tsx"),
    "JWT revocation":                  "revoked:" in Path("backend/services/auth_service.py").read_text(encoding="utf-8") if file_exists("backend/services/auth_service.py") else False,
    # P2
    "signal_stacker.py":              file_exists("ml/models/ensemble/signal_stacker.py"),
    "model_retraining_service.py":    file_exists("backend/services/model_retraining_service.py"),
    "binance_collector.py":           file_exists("data_pipeline/collectors/binance_collector.py"),
    "alphavantage_collector.py":      file_exists("data_pipeline/collectors/alphavantage_collector.py"),
    # P3
    "metrics.py":                     file_exists("backend/monitoring/metrics.py"),
    "monitoring.py router":           file_exists("backend/api/routers/monitoring.py"),
    "003_ohlcv_index.py":             file_exists("alembic/versions/003_ohlcv_index.py"),
    "setup_tls.sh":                   file_exists("deployment/scripts/setup_tls.sh"),
    "backup.sh":                      file_exists("deployment/scripts/backup.sh"),
    # P4
    "mobile package.json":            file_exists("apps/mobile/package.json"),
    "PortfolioScreen.tsx":            file_exists("apps/mobile/src/screens/PortfolioScreen.tsx"),
    "WatchlistScreen.tsx":            file_exists("apps/mobile/src/screens/WatchlistScreen.tsx"),
    "SettingsScreen.tsx":             file_exists("apps/mobile/src/screens/SettingsScreen.tsx"),
    "AppNavigator.tsx":               file_exists("apps/mobile/src/navigation/AppNavigator.tsx"),
    "notifications.py router":        file_exists("backend/api/routers/notifications.py"),
    "004_device_tokens.py":           file_exists("alembic/versions/004_device_tokens.py"),
    "device_token.py ORM":            file_exists("backend/models/device_token.py"),
}

for k, v in checks.items():
    print(f"{'[PASS]' if v else '[FAIL]'} {k}")

passed = sum(checks.values())
print(f"\n{passed}/{len(checks)} checks passed")
