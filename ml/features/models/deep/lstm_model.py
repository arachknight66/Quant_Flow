# ml/models/deep/lstm_model.py
"""
LSTM (Long Short-Term Memory) for return direction prediction.

When to use LSTM vs XGBoost:
- XGBoost: works on tabular features at a single timestep
- LSTM: directly processes sequences — learns temporal patterns
  that manual feature engineering might miss

Practical reality: In most financial prediction tasks, XGBoost with
good features beats LSTM. LSTMs require far more data, are harder
to tune, overfit more easily, and are opaque.

Use LSTM when:
  1. You have > 5 years of daily data (> 1250 bars)
  2. You've exhausted feature engineering for XGBoost
  3. You want to learn raw price patterns rather than engineered features
  4. You're building an ensemble (LSTM + XGBoost blended)

DO NOT use LSTM when:
  1. You have < 500 samples
  2. You haven't validated XGBoost walk-forward first
  3. You think it will magically discover hidden patterns

Architecture choices:
  - 2 LSTM layers (deeper rarely helps for financial data)
  - Layer normalisation (more stable than batch norm for sequences)
  - Dropout 0.2 on LSTM output (temporal dropout would also work)
  - Dense output with sigmoid activation (binary classification)
  - Sequence length 60 days (configurable)
"""
import numpy as np
import pandas as pd
from typing import Optional, Tuple
import structlog
import json
from pathlib import Path

log = structlog.get_logger()

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, DataLoader
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    log.warning("PyTorch not available. Install: pip install torch")


if TORCH_AVAILABLE:
    class FinancialLSTM(nn.Module):
        """
        LSTM network for binary financial prediction.

        Architecture:
            Input: (batch, seq_len, n_features)
            LSTM Layer 1: hidden_size units, returns sequences
            LayerNorm → Dropout
            LSTM Layer 2: hidden_size units, returns last state
            LayerNorm → Dropout
            Dense(hidden_size/2) → ReLU
            Dense(1) → Sigmoid

        Why LayerNorm instead of BatchNorm?
        BatchNorm normalises across the batch dimension — problematic
        for sequences and small batches. LayerNorm normalises across
        the feature dimension — stable regardless of batch size.
        """

        def __init__(
            self,
            n_features: int,
            hidden_size: int = 128,
            n_layers: int = 2,
            dropout: float = 0.2,
            sequence_length: int = 60,
        ):
            super().__init__()
            self.hidden_size = hidden_size
            self.n_layers = n_layers
            self.sequence_length = sequence_length

            self.lstm = nn.LSTM(
                input_size=n_features,
                hidden_size=hidden_size,
                num_layers=n_layers,
                batch_first=True,      # (batch, seq, features)
                dropout=dropout if n_layers > 1 else 0.0,
            )
            self.layer_norm = nn.LayerNorm(hidden_size)
            self.dropout = nn.Dropout(dropout)

            self.classifier = nn.Sequential(
                nn.Linear(hidden_size, hidden_size // 2),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_size // 2, 1),
                nn.Sigmoid(),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (batch_size, seq_len, n_features)
            lstm_out, _ = self.lstm(x)
            # Take only the last timestep's output
            last_out = lstm_out[:, -1, :]
            normed = self.layer_norm(last_out)
            dropped = self.dropout(normed)
            return self.classifier(dropped).squeeze(-1)


    class FinancialSequenceDataset(Dataset):
        """
        PyTorch Dataset that creates sliding window sequences.

        For each bar at position i, creates a sequence of the
        previous `seq_len` bars' features, labelled with the
        binary outcome at bar i.

        CRITICAL: Target for sequence ending at bar i must be
        based on bar i+horizon CLOSE, not anything in [i-seq_len:i].
        The target is EXCLUDED from the input sequence.
        """

        def __init__(
            self,
            features: np.ndarray,
            targets: np.ndarray,
            seq_len: int = 60,
        ):
            self.features = features.astype(np.float32)
            self.targets = targets.astype(np.float32)
            self.seq_len = seq_len

            # Valid range: need seq_len bars before + target at the end
            self.valid_indices = list(range(seq_len, len(targets)))

        def __len__(self):
            return len(self.valid_indices)

        def __getitem__(self, idx):
            end = self.valid_indices[idx]
            start = end - self.seq_len
            X = self.features[start:end]
            y = self.targets[end - 1]
            return torch.FloatTensor(X), torch.FloatTensor([y])


class LSTMSignalModel:
    """
    Complete LSTM training and inference pipeline.

    Walk-forward validation is even more critical here than for XGBoost —
    LSTMs have much higher capacity to memorize training data.
    """

    def __init__(
        self,
        sequence_length: int = 60,
        hidden_size: int = 128,
        n_layers: int = 2,
        dropout: float = 0.2,
        prediction_horizon: int = 5,
        learning_rate: float = 1e-3,
        n_epochs: int = 50,
        batch_size: int = 32,
        early_stopping_patience: int = 10,
        version: str = "lstm_v1",
    ):
        self.seq_len = sequence_length
        self.hidden_size = hidden_size
        self.n_layers = n_layers
        self.dropout = dropout
        self.horizon = prediction_horizon
        self.lr = learning_rate
        self.n_epochs = n_epochs
        self.batch_size = batch_size
        self.patience = early_stopping_patience
        self.version = version

        self._model: Optional["FinancialLSTM"] = None
        self._feature_scaler = None
        self._feature_names: list[str] = []
        self._device = "cuda" if (TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu"

        log.info("LSTM device", device=self._device)

    def _create_target(self, close: pd.Series) -> np.ndarray:
        """Binary target: forward return > 1% over horizon."""
        future_return = close.shift(-self.horizon) / close - 1
        target = (future_return > 0.01).astype(float)
        target.iloc[-self.horizon:] = np.nan
        return target.values

    def _select_features(self, features: pd.DataFrame) -> pd.DataFrame:
        """Same stationary feature selection as XGBoost model."""
        prefixes = [
            "log_return_", "rsi", "macd_hist", "bb_pct_b", "bb_width",
            "atr_pct", "price_ema_", "price_sma_", "vol_", "momentum_",
            "roc", "volume_ratio",
        ]
        selected = [
            col for col in features.columns
            if any(col.startswith(p) or col == p.rstrip("_") for p in prefixes)
        ]
        return features[selected]

    def train(
        self,
        features: pd.DataFrame,
        close: pd.Series,
        val_split: float = 0.15,
    ) -> dict:
        """
        Train LSTM with walk-forward-like train/val split.

        The validation set is always the LAST val_split fraction of data
        (temporal split, never random). Early stopping uses val loss.
        """
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch required for LSTM training.")

        from sklearn.preprocessing import StandardScaler

        ml_features = self._select_features(features)
        self._feature_names = list(ml_features.columns)

        # Scale features
        self._feature_scaler = StandardScaler()
        X_scaled = self._feature_scaler.fit_transform(ml_features.values)

        # Target
        y = self._create_target(close)

        # Drop NaN rows (from horizon shift and indicator warmup)
        valid = ~np.isnan(y) & ~np.isnan(X_scaled).any(axis=1)
        X_valid = X_scaled[valid]
        y_valid = y[valid]

        if len(X_valid) < self.seq_len + 100:
            raise ValueError(f"Insufficient valid data: {len(X_valid)} rows")

        # Temporal split
        split_idx = int(len(X_valid) * (1 - val_split))

        train_ds = FinancialSequenceDataset(
            X_valid[:split_idx], y_valid[:split_idx], self.seq_len
        )
        val_ds = FinancialSequenceDataset(
            X_valid[split_idx - self.seq_len:],  # Keep overlap for context
            y_valid[split_idx - self.seq_len:],
            self.seq_len,
        )

        train_loader = DataLoader(
            train_ds, batch_size=self.batch_size, shuffle=False,  # Never shuffle time-series
            num_workers=0,
        )
        val_loader = DataLoader(val_ds, batch_size=self.batch_size, shuffle=False)

        # Model
        self._model = FinancialLSTM(
            n_features=len(self._feature_names),
            hidden_size=self.hidden_size,
            n_layers=self.n_layers,
            dropout=self.dropout,
            sequence_length=self.seq_len,
        ).to(self._device)

        # Optimizer + scheduler
        optimizer = torch.optim.Adam(self._model.parameters(), lr=self.lr, weight_decay=1e-5)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, patience=5, factor=0.5, min_lr=1e-5
        )

        # Class weight for imbalanced target
        pos_weight = torch.tensor(
            [(y_valid == 0).sum() / max((y_valid == 1).sum(), 1)],
            device=self._device
        )
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        # Training loop with early stopping
        best_val_loss = float("inf")
        best_state = None
        patience_counter = 0
        history = {"train_loss": [], "val_loss": []}

        for epoch in range(self.n_epochs):
            # Training
            self._model.train()
            train_losses = []
            for X_batch, y_batch in train_loader:
                X_batch = X_batch.to(self._device)
                y_batch = y_batch.squeeze(-1).to(self._device)

                optimizer.zero_grad()
                logits = self._model(X_batch)

                # Use raw logits with BCEWithLogitsLoss (numerically stable)
                loss = criterion(logits, y_batch)
                loss.backward()

                # Gradient clipping — critical for LSTM (exploding gradients)
                torch.nn.utils.clip_grad_norm_(self._model.parameters(), max_norm=1.0)

                optimizer.step()
                train_losses.append(loss.item())

            # Validation
            self._model.eval()
            val_losses = []
            with torch.no_grad():
                for X_batch, y_batch in val_loader:
                    X_batch = X_batch.to(self._device)
                    y_batch = y_batch.squeeze(-1).to(self._device)
                    logits = self._model(X_batch)
                    loss = criterion(logits, y_batch)
                    val_losses.append(loss.item())

            train_loss = np.mean(train_losses)
            val_loss = np.mean(val_losses)
            scheduler.step(val_loss)

            history["train_loss"].append(round(float(train_loss), 5))
            history["val_loss"].append(round(float(val_loss), 5))

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_state = {k: v.cpu().clone() for k, v in self._model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= self.patience:
                    log.info("Early stopping", epoch=epoch, val_loss=round(val_loss, 5))
                    break

            if epoch % 10 == 0:
                log.info(
                    "LSTM training",
                    epoch=epoch,
                    train_loss=round(train_loss, 5),
                    val_loss=round(val_loss, 5),
                )

        # Restore best model
        if best_state:
            self._model.load_state_dict(best_state)

        return {
            "epochs_trained": len(history["train_loss"]),
            "best_val_loss": round(best_val_loss, 5),
            "history": history,
            "n_features": len(self._feature_names),
            "n_train_sequences": len(train_ds),
            "n_val_sequences": len(val_ds),
        }

    def predict(self, features: pd.DataFrame) -> dict:
        """Run inference on the last seq_len bars of features."""
        if not TORCH_AVAILABLE or self._model is None:
            raise RuntimeError("Model not trained.")

        from sklearn.preprocessing import StandardScaler

        ml_features = self._select_features(features)[self._feature_names]
        X_scaled = self._feature_scaler.transform(ml_features.values)

        if len(X_scaled) < self.seq_len:
            raise ValueError(f"Need at least {self.seq_len} bars, got {len(X_scaled)}")

        X_seq = X_scaled[-self.seq_len:]
        X_tensor = torch.FloatTensor(X_seq).unsqueeze(0).to(self._device)

        self._model.eval()
        with torch.no_grad():
            prob = float(torch.sigmoid(
                self._model(X_tensor)
            ).cpu().item())

        if prob > 0.60:
            action = "BUY"
        elif prob < 0.40:
            action = "SELL"
        else:
            action = "HOLD"

        return {
            "action": action,
            "prob_profit": round(prob, 4),
            "confidence": round(abs(prob - 0.5) * 2, 4),
            "model_version": self.version,
        }