"""Statistics for independent paired subjects within each contrast."""
from __future__ import annotations

import numpy as np
from scipy import stats


def paired_statistics(a, b, *, bootstrap=2000, seed=2026, threshold=None, tolerance=None):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != b.shape or a.ndim != 1 or not np.isfinite([a, b]).all():
        raise ValueError("Expected equal-length finite paired vectors")
    n = len(a)
    if n == 0:
        return {"n": 0}
    delta = b - a
    result = dict(n=n, mean_baseline=float(a.mean()), mean_variant=float(b.mean()),
                  mean_difference=float(delta.mean()), mean_absolute_difference=float(abs(delta).mean()),
                  median_difference=float(np.median(delta)),
                  rmse_difference=float(np.sqrt(np.mean(delta ** 2))),
                  p95_absolute_difference=float(np.quantile(abs(delta), .95)),
                  sd_difference=None, wilcoxon_p=None, pearson_r=None, spearman_r=None,
                  concordance=None, icc_a1=None)
    if n >= 2:
        sd = float(delta.std(ddof=1))
        result.update(sd_difference=sd, loa_lower=float(delta.mean()-1.96*sd),
                      loa_upper=float(delta.mean()+1.96*sd))
        # Explicit zero handling avoids scipy warnings and undefined all-zero tests.
        result["wilcoxon_p"] = float(stats.wilcoxon(delta, zero_method="wilcox", method="auto").pvalue) if np.any(delta) else 1.0
        if np.std(a) > 0 and np.std(b) > 0:
            result["pearson_r"] = float(stats.pearsonr(a, b).statistic)
            result["spearman_r"] = float(stats.spearmanr(a, b).statistic)
        denominator = a.var() + b.var() + (a.mean()-b.mean())**2
        if denominator > 0:
            result["concordance"] = float(2*np.mean((a-a.mean())*(b-b.mean()))/denominator)
        # Two-way absolute agreement, single measurement ICC(A,1), k=2.
        values = np.column_stack((a, b)); grand = values.mean()
        rows, cols = values.mean(axis=1), values.mean(axis=0)
        msr = 2*np.sum((rows-grand)**2)/(n-1)
        msc = n*np.sum((cols-grand)**2)
        mse = np.sum((values-rows[:, None]-cols[None, :]+grand)**2)/(n-1)
        denom = msr + mse + 2*(msc-mse)/n
        if denom > 0:
            result["icc_a1"] = float((msr-mse)/denom)
        rng = np.random.default_rng(seed)
        estimates = []
        for start in range(0, bootstrap, 256):
            samples = delta[rng.integers(0, n, size=(min(256, bootstrap-start), n))]
            estimates.append(np.column_stack((samples.mean(axis=1), abs(samples).mean(axis=1))))
        ci = np.quantile(np.concatenate(estimates), [.025, .975], axis=0)
        result.update(mean_difference_ci_low=float(ci[0, 0]), mean_difference_ci_high=float(ci[1, 0]),
                      mad_ci_low=float(ci[0, 1]), mad_ci_high=float(ci[1, 1]))
    if threshold is not None:
        result.update(decision_threshold=threshold, flip_rate=float(np.mean((a >= threshold) != (b >= threshold))))
    if tolerance is not None:
        result.update(absolute_tolerance=tolerance, fraction_within_tolerance=float(np.mean(abs(delta) <= tolerance)))
    return result


def adjust_bh(rows):
    """BH FDR across every task/contrast tested in this report (one family)."""
    tested = [(i, r["wilcoxon_p"]) for i, r in enumerate(rows) if r.get("wilcoxon_p") is not None]
    tested.sort(key=lambda item: item[1])
    running = 1.0
    for rank in range(len(tested), 0, -1):
        index, p = tested[rank-1]
        running = min(running, p*len(tested)/rank)
        rows[index]["wilcoxon_q_bh"] = running
