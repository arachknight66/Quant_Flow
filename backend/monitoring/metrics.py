from prometheus_client import Counter, Gauge

signal_counter    = Counter("qp_signals_total", "Total signals", ["action", "symbol"])
ws_connections    = Gauge("qp_ws_connections", "Active WebSocket connections")
cache_hits        = Counter("qp_cache_hits_total", "Redis cache hits", ["symbol"])
cache_misses      = Counter("qp_cache_misses_total", "Redis cache misses", ["symbol"])
model_predictions = Counter("qp_model_predictions_total", "Model predictions", ["symbol", "model_version"])
