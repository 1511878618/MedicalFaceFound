"""Probability calibration and research risk tiers from released task configs.

A released ``config.json`` may carry two optional blocks::

    "calibration": {"method": "platt_on_logit_nonnegative_slope",
                    "a": 1.63, "b": 2.74, "eps": 1e-06, ...}
    "stratification": {"cutoffs": [0.63, 0.81, 0.95],
                       "labels": ["Very low", "Low", "Moderate", "High"],
                       "comparator": ">=", ...}

The blocks are optional: models without them return ``None`` and existing behaviour is unchanged.
Probability calibration and tier cutoffs are research candidates fitted on one development cohort;
the labels are not a clinical decision rule.
"""

from __future__ import annotations

import bisect

import numpy as np

__all__ = [
    "has_calibration",
    "has_stratification",
    "calibrate_probabilities",
    "assign_tiers",
]


def has_calibration(cfg: dict) -> bool:
    """True when the config carries a calibration block."""
    return isinstance(cfg.get("calibration"), dict)


def has_stratification(cfg: dict) -> bool:
    """True when the config carries a stratification block."""
    return isinstance(cfg.get("stratification"), dict)


def _read_calibration(cfg: dict) -> tuple[float, float, float]:
    block = cfg["calibration"]
    try:
        a = float(block["a"])
        b = float(block["b"])
    except KeyError as exc:
        raise ValueError(f"calibration block is missing {exc.args[0]!r}") from None
    eps = float(block.get("eps", 1e-06))
    if not np.isfinite([a, b, eps]).all():
        raise ValueError("calibration a/b/eps must be finite")
    if a < 0:
        raise ValueError("calibration slope a must be non-negative to preserve event direction")
    if not 0.0 < eps < 0.5:
        raise ValueError("calibration eps must lie in (0, 0.5)")
    return a, b, eps


def _read_stratification(cfg: dict) -> tuple[list[float], list[str], str]:
    block = cfg["stratification"]
    cutoffs = [float(c) for c in block["cutoffs"]]
    labels = [str(label) for label in block["labels"]]
    comparator = str(block.get("comparator", ">="))
    if not cutoffs:
        raise ValueError("stratification needs at least one cutoff")
    if not np.isfinite(cutoffs).all():
        raise ValueError("stratification cutoffs must be finite")
    if any(lo >= hi for lo, hi in zip(cutoffs, cutoffs[1:])):
        raise ValueError("stratification cutoffs must be strictly increasing")
    if len(labels) != len(cutoffs) + 1:
        raise ValueError(
            f"stratification labels ({len(labels)}) must be one more than cutoffs ({len(cutoffs)})")
    if comparator not in (">=", ">"):
        raise ValueError("stratification comparator must be '>=' or '>'")
    return cutoffs, labels, comparator


def calibrate_probabilities(probabilities, cfg: dict):
    """Apply ``sigmoid(a * logit(clip(p, eps, 1-eps)) + b)``.

    Returns ``None`` when ``cfg`` has no calibration block, so callers can keep the raw score.
    Accepts a scalar or an array-like of probabilities.
    """
    if not has_calibration(cfg):
        return None
    a, b, eps = _read_calibration(cfg)
    p = np.clip(np.asarray(probabilities, dtype=float), eps, 1.0 - eps)
    z = a * np.log(p / (1.0 - p)) + b
    # expit(z) = 1 / (1 + exp(-z)), evaluated through logaddexp to avoid overflow.
    return np.exp(-np.logaddexp(0.0, -z))


def assign_tiers(calibrated, cfg: dict):
    """Map calibrated probabilities to their tier labels.

    Returns ``None`` when ``cfg`` has no stratification block. Accepts a scalar or an array-like;
    the return value mirrors the input (single label for a scalar, list of labels otherwise).
    """
    if not has_stratification(cfg):
        return None
    cutoffs, labels, comparator = _read_stratification(cfg)
    scalar = np.ndim(calibrated) == 0
    values = np.atleast_1d(np.asarray(calibrated, dtype=float)).ravel()
    pick = bisect.bisect_right if comparator == ">=" else bisect.bisect_left
    tiers = [labels[pick(cutoffs, float(v))] for v in values]
    return tiers[0] if scalar else tiers
