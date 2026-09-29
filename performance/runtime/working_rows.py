"""Research LP: keep the full matrix, solve a growing row subset, check ALL rows.

Numerical optimization only. Independent geometric certification is unchanged.
"""
from time import perf_counter
import hashlib
import numpy as np
import highspy
from master import Solution


def seed_dual(master, checkpoint):
    """Map a saved dual to an extended model; this is only a row-selection seed."""
    for key in ('L', 'B', 'rhs'):
        if key not in checkpoint or float(checkpoint[key]) != getattr(master, key):
            raise ValueError('dual seed geometry mismatch')
    poses, rectangles = checkpoint['poses'], checkpoint['rectangles']
    dual = np.asarray(checkpoint['dual'])
    if (dual.shape != (len(poses),) or not np.isfinite(dual).all()
            or np.any(dual < 0)
            or not np.array_equal(master.poses[:len(poses)], poses)
            or not np.array_equal(master.rectangles[:len(rectangles)], rectangles)):
        raise ValueError('dual seed must match a retained model prefix')
    return np.pad(dual, (0, len(master.poses)-len(poses)))


def _prefix_digest(A, rows, rhs):
    """Exact finite-model identity, including explicitly stored tiny coefficients."""
    digest = hashlib.sha256(repr((A.shape[1], rows, rhs)).encode())
    end = A.indptr[rows]
    for values in (A.indptr[:rows+1], A.indices[:end], A.data[:end]):
        digest.update(values.dtype.str.encode())
        digest.update(np.ascontiguousarray(values).view(np.uint8))
    return digest.digest()


def solve_working_rows(master, initial_dual, batch=256, max_rounds=100, reuse=False):
    if batch < 1 or max_rounds < 1 or len(master.atoms):
        raise ValueError('positive limits and rectangle-only model required')
    dual = np.asarray(initial_dual)
    if dual.shape != (len(master.poses),) or not np.isfinite(dual).all() or np.any(dual < 0):
        raise ValueError('invalid initial dual')
    started = perf_counter()
    A = master.A.tocsr()
    cache = getattr(master, '_working_rows_cache', None) if reuse else None
    # Detach first: exceptions must never leave partially modified solver state reusable.
    if reuse and hasattr(master, '_working_rows_cache'):
        del master._working_rows_cache
    # Bound retained working rows over long runs. The complete matrix stays in
    # master.A; exceeding this limit simply uses the original cold initialization.
    warm = (cache is not None and len(cache['selected']) <= max(4096, 2*A.shape[1])
            and cache['rows'] <= A.shape[0]
            and cache['digest'] == _prefix_digest(A, cache['rows'], master.rhs))
    if not warm:
        cache = None
    h = cache['h'] if warm else highspy.Highs()
    check = master._check
    for key, value in [('output_flag', False), ('threads', 1), ('solver', 'simplex'),
                       ('primal_feasibility_tolerance', 1e-9),
                       ('dual_feasibility_tolerance', 1e-9), ('small_matrix_value', 1e-12)]:
        check(h.setOptionValue(key, value))
    n = A.shape[1]
    if not warm:
        check(h.addCols(n, np.ones(n), np.zeros(n), np.full(n, np.inf), 0,
                       np.zeros(n+1, np.int32), np.array([], np.int32), np.array([], float)))
    selected = cache['selected'].copy() if warm else []
    used = np.zeros(A.shape[0], dtype=bool)
    used[selected] = True
    pending = np.flatnonzero((dual > 0) & ~used)
    if not len(pending) and not warm: pending = np.arange(min(batch, A.shape[0]))
    history = []
    for iteration in range(max_rounds):
        block = A[pending]
        if len(pending):
            check(h.addRows(len(pending), np.full(len(pending), master.rhs),
                           np.full(len(pending), np.inf), block.nnz,
                           block.indptr.astype(np.int32), block.indices.astype(np.int32), block.data))
        selected.extend(pending.tolist()); used[pending] = True
        check(h.run())
        if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
            raise RuntimeError(f'working LP status {h.getModelStatus()}')
        s = h.getSolution()
        weights = np.maximum(np.asarray(s.col_value), 0.)
        full_dual = np.zeros(A.shape[0]); full_dual[selected] = np.maximum(s.row_dual, 0.)
        coverage = A @ weights
        minimum = float(coverage.min())
        violation = max(0., float((A.T @ full_dual).max())-1.)
        mass = float(weights.sum()); gap = mass-master.rhs*float(full_dual.sum())
        history.append(dict(iteration=iteration, rows=len(selected), mass=mass, minimum=minimum))
        if minimum >= master.rhs-2e-7:
            # Same nonnegative clipping and final primal rescaling as Master.
            if minimum < master.rhs:
                weights *= master.rhs/minimum
                minimum = float((A @ weights).min())
                mass = float(weights.sum()); gap = mass-master.rhs*float(full_dual.sum())
            if (not np.isfinite(weights).all() or not np.isfinite(full_dual).all()
                    or np.any(weights < 0) or np.any(full_dual < 0)
                    or violation > 2e-5 or abs(gap) > 1e-4):
                raise RuntimeError(f'original full-model residual gates failed: min={minimum}, dual={violation}, gap={gap}')
            if reuse:
                master._working_rows_cache = dict(h=h, selected=selected.copy(), rows=A.shape[0],
                                                  digest=_prefix_digest(A, A.shape[0], master.rhs))
            result = Solution(weights, full_dual, mass, perf_counter()-started,
                              h.getInfo().simplex_iteration_count, minimum, violation, gap)
            return result, dict(status='FULL_FINITE_MODEL_CHECKED', full_rows=A.shape[0],
                                working_rows=len(selected), rounds=len(history), history=history,
                                reused_solver=bool(warm))
        bad = np.flatnonzero((coverage < master.rhs-2e-7) & ~used)
        if not len(bad): raise RuntimeError('violated existing working row')
        pending = bad[np.argsort(coverage[bad], kind='stable')[:batch]]
    raise RuntimeError('working-row review limit; no accepted solution')
