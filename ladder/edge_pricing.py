"""Optional four-edge pricing for rectangle Masters; never a proof oracle.

Retains every existing column. Uses every positive dual row, then the caller
must re-solve on ALL constraints with the original residual gates.
Import with the chosen rectangle engine directory on sys.path.
"""
from time import perf_counter
import numpy as np
from scipy.optimize import minimize
from geometry import Geometry, rectangle_key
from pricing import scores


def propose_edges(master, solution, *, max_columns=32, seed_count=48,
                  local_starts=8, max_evaluations=120, relative_step=.15,
                  margin=.001, min_side=.001):
    if (max_columns < 1 or seed_count < 1 or local_starts < 0
            or max_evaluations < 5 or not 0 < relative_step < .5
            or not 1/20000 < margin < master.L/2
            or not np.isfinite(min_side) or not 0 <= min_side < master.L-2*margin):
        raise ValueError('invalid pricing settings')
    if len(getattr(master, 'atoms', [])):
        raise ValueError('rectangle-only pricing')
    t = perf_counter()
    weights = np.asarray(solution.weights)[master.rect_cols]
    dual = np.asarray(solution.dual)
    if (weights.shape != (len(master.rectangles),)
            or dual.shape != (len(master.poses),)
            or not np.isfinite(weights).all() or not np.isfinite(dual).all()
            or np.any(weights < 0) or np.any(dual < 0)):
        raise ValueError('invalid LP solution')
    ids = np.flatnonzero(weights > 0)
    ids = ids[np.argsort(-weights[ids], kind='stable')[:seed_count]]
    side_floor = max(min_side, 1e-6 * master.L)
    pool, seen = [], set(master.rect_keys)
    def valid(r):
        return (np.isfinite(r).all() and np.all(r[:2] >= margin)
                and np.all(r[2:] <= master.L-margin)
                and np.all(r[2:]-r[:2] >= side_floor))
    # One-edge moves can alter width AND center without moving the opposite edge.
    for i in ids:
        r = master.rectangles[i]
        step = np.tile(r[2:]-r[:2], 2) * relative_step
        for edge in range(4):
            for sign in (-1, 1):
                trial = r.copy(); trial[edge] += sign*step[edge]
                if not valid(trial):
                    continue
                key = rectangle_key(trial, master.L)
                if key not in seen:
                    seen.add(key); pool.append(trial)
    if not pool:
        return [], dict(status='HEURISTIC_PRICING', columns=0,
                        evaluations=0, seconds=perf_counter()-t)
    values = scores(master.L, master.B, pool, master.poses, dual)
    evaluations = len(pool)
    ranked = sorted(zip(pool, values), key=lambda x: -x[1])
    proposals = list(ranked)
    for r, _ in ranked[:local_starts]:
        scale = np.tile(r[2:]-r[:2], 2) / master.L * relative_step
        x = r/master.L
        simplex = np.tile(x, (5, 1))
        for j in range(4):
            sign = -1 if j < 2 else 1
            simplex[j+1, j] = np.clip(x[j]+sign*scale[j], margin/master.L, 1-margin/master.L)
            if simplex[j+1, j] == x[j]:
                simplex[j+1, j] = np.clip(x[j]-sign*scale[j], margin/master.L, 1-margin/master.L)
        def objective(z):
            trial = z*master.L
            if not valid(trial):
                return 1e6
            return -float(scores(master.L, master.B, [trial], master.poses, dual)[0])
        opt = minimize(objective, x, method='Nelder-Mead',
                       bounds=[(margin/master.L, 1-margin/master.L)]*4,
                       options=dict(initial_simplex=simplex, maxfev=max_evaluations,
                                    xatol=1e-7, fatol=1e-8))
        evaluations += opt.nfev
        trial = opt.x*master.L
        if valid(trial):
            proposals.append((trial, -float(opt.fun)))
    selected, seen = [], set(master.rect_keys)
    for r, score in sorted(proposals, key=lambda x: -x[1]):
        if score <= 1+1e-6:
            continue
        key = rectangle_key(r, master.L)
        if key in seen:
            continue
        Geometry(master.L, master.B, [r])
        seen.add(key)
        selected.append(dict(rectangle=r.tolist(), score=float(score)))
        if len(selected) >= max_columns:
            break
    return selected, dict(status='HEURISTIC_PRICING', columns=len(selected),
                          min_side=side_floor, margin=margin,
                          evaluations=int(evaluations), seeds=len(ids),
                          positive_dual_rows=int(np.count_nonzero(dual > 0)),
                          best_score=max((x['score'] for x in selected), default=None),
                          seconds=perf_counter()-t)
