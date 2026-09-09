from __future__ import annotations

class OnlineRidge:
    """Optional online-weight-update ablation; requires genuine scalar target feedback.

    Recursive least squares, one deployment example per update. No offline fit.
    This is an established baseline, not the proposed novel contribution.
    No claim of no-forgetting within one scope. Independent objects isolate scopes.
    """
    def __init__(self, dimension: int, regularization: float = 1.0):
        import numpy as np
        if dimension < 1 or regularization <= 0:
            raise ValueError("invalid dimensions or regularization")
        self.np = np
        self.inverse = np.eye(dimension, dtype=float) / regularization
        self.weights = np.zeros(dimension, dtype=float)
        self.count = 0

    def predict(self, features) -> float:
        x = self.np.asarray(features, dtype=float)
        if x.shape != self.weights.shape or not self.np.isfinite(x).all():
            raise ValueError("invalid feature vector")
        return float(x @ self.weights)

    def observe(self, features, *, target: float | None) -> None:
        if target is None:
            raise ValueError("a failed action does not reveal a regression target")
        x = self.np.asarray(features, dtype=float)
        pred = self.predict(x)
        if not self.np.isfinite(target):
            raise ValueError("nonfinite target")
        px = self.inverse @ x
        denom = 1.0 + float(x @ px)
        self.weights += (px / denom) * (float(target) - pred)
        self.inverse -= self.np.outer(px, px) / denom
        self.inverse = (self.inverse + self.inverse.T) / 2.0
        self.count += 1
