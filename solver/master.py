"""b: persistent LP with cached coverage entries and incremental rows/columns."""
from dataclasses import dataclass
from time import perf_counter
import hashlib
import json
import os
from pathlib import Path
from residual_dump import save_failure
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from geometry import Geometry, rectangle_key
import points


@dataclass
class Solution:
    weights: np.ndarray
    dual: np.ndarray
    mass: float
    seconds: float
    iterations: int
    min_coverage: float
    dual_violation: float
    duality_gap: float


class Master:
    def __init__(self, L, B, rectangles, rhs=1.001, backend='highs',
                 atoms=None, atom_weights=None, atom_mode='fixed'):
        """Covering LP over rectangle densities, optionally with point atoms.

        Atoms enter as extra columns: a second family of valid inequalities
        over the same disjoint cores, so the two budgets add rather than one
        replacing the other. That is what lets an existing point certificate
        seed a ladder without being converted into rectangles -- see points.py.

        `atom_mode` 'fixed' pins the atoms at the weights they arrive with;
        'free' lets the LP reassign them.
        """
        if not np.isfinite(rhs) or rhs <= 0:
            raise ValueError('rhs must be positive')
        self.L, self.B, self.rhs = L, B, rhs
        self.rectangles = Geometry(L, B, rectangles).rectangles.copy()
        if atoms is None:
            self.atoms = np.empty((0, 2))
            self.atom_weights = np.empty(0)
        else:
            self.atoms = np.asarray(atoms, float).reshape(-1, 2)
            if atom_weights is None:
                raise ValueError('atoms need weights')
            self.atom_weights = np.asarray(atom_weights, float).reshape(-1)
            if len(self.atom_weights) != len(self.atoms):
                raise ValueError('one weight per atom')
        self.atom_mode = atom_mode
        self.atom_lo, self.atom_hi = points.bounds(self.atom_weights, atom_mode)
        self.poses = np.empty((0, 3))
        self.A = sparse.csr_matrix((0, len(self.rectangles) + len(self.atoms)))
        # Column index of each rectangle; atoms occupy the rest.
        self.rect_cols = np.arange(len(self.rectangles))
        self.atom_cols = np.arange(len(self.atoms)) + len(self.rectangles)
        self.pose_keys = set()
        self.rect_keys = {rectangle_key(r, L) for r in self.rectangles}
        self.backend = backend
        self.geometry_seconds = 0.
        self.entries_evaluated = 0
        self.tiny_entries_dropped = 0
        # Residual-failure captures must outlive the run, so they are not written
        # next to the module (the solver directory may be a temporary copy).
        # SP_RESIDUAL_DUMP_DIR overrides; otherwise ./captures under the current
        # working directory.
        self.residual_dump_dir = Path(os.environ.get('SP_RESIDUAL_DUMP_DIR')
                                      or Path.cwd()/'captures')
        self.h = None
        if backend == 'highs':
            import highspy
            self.h = highspy.Highs()
            for name, value in [('output_flag', False), ('solver', 'simplex'),
                                ('threads', 1), ('random_seed', 0),
                                ('small_matrix_value', 1e-12),
                                ('primal_feasibility_tolerance', 1e-9),
                                ('dual_feasibility_tolerance', 1e-9)]:
                self._check(self.h.setOptionValue(name, value))
            n = len(self.rectangles)
            self._check(self.h.addCols(n, np.ones(n), np.zeros(n), np.full(n, np.inf),
                                      0, np.zeros(n+1, np.int32), np.array([], np.int32),
                                      np.array([], float)))
            m = len(self.atoms)
            if m:
                self._check(self.h.addCols(m, np.ones(m), self.atom_lo, self.atom_hi,
                                          0, np.zeros(m+1, np.int32),
                                          np.array([], np.int32), np.array([], float)))
        elif backend != 'scipy':
            raise ValueError('backend must be highs or scipy')

    @staticmethod
    def _check(status):
        import highspy
        if status != highspy.HighsStatus.kOk:
            raise RuntimeError(f'HiGHS call failed: {status}')

    def _matrix(self, poses, rectangles, with_atoms=False):
        start = perf_counter()
        block = Geometry(self.L, self.B, rectangles).matrix(poses)
        if with_atoms and len(self.atoms):
            block = np.hstack([block, points.columns(
                poses, self.L, self.B, self.atoms, np.ones(len(self.atoms)))])
        result = sparse.csr_matrix(block)
        # Match HiGHS' smallest supported coefficient threshold explicitly,
        # so the cached LP and the actual solver never silently diverge.
        tiny = np.abs(result.data) <= 1e-12
        self.tiny_entries_dropped += int(np.count_nonzero(tiny))
        result.data[tiny] = 0
        result.eliminate_zeros()
        self.geometry_seconds += perf_counter()-start
        self.entries_evaluated += len(poses)*len(rectangles)
        return result

    def add_rows(self, poses):
        poses = np.asarray(poses, float).reshape(-1, 3)
        # Validate before modifying state; rounding affects deduplication only.
        if (not np.isfinite(poses).all() or np.any(np.abs(poses[:, :2]) > 1)
                or np.any(poses[:, 2] < 0) or np.any(poses[:, 2] > 1)):
            raise ValueError('Invalid poses')
        fresh, keys = [], set()
        for p in poses:
            key = tuple(np.round(p, 12))
            if key not in self.pose_keys and key not in keys:
                fresh.append(p); keys.add(key)
        if not fresh:
            return 0
        fresh = np.asarray(fresh)
        block = self._matrix(fresh, self.rectangles, with_atoms=True)
        if self.h is not None:
            self._check(self.h.addRows(len(fresh), np.full(len(fresh), self.rhs),
                                      np.full(len(fresh), np.inf), block.nnz,
                                      block.indptr.astype(np.int32), block.indices.astype(np.int32), block.data))
        self.A = sparse.vstack([self.A, block], format='csr')
        self.poses = np.vstack([self.poses, fresh])
        self.pose_keys.update(keys)
        return len(fresh)

    def add_columns(self, rectangles):
        rectangles = Geometry(self.L, self.B, rectangles).rectangles
        fresh, keys = [], set()
        for r in rectangles:
            key = rectangle_key(r, self.L)
            if key not in self.rect_keys and key not in keys:
                fresh.append(r); keys.add(key)
        if not fresh:
            return 0
        fresh = np.asarray(fresh)
        block = self._matrix(self.poses, fresh).tocsc()
        if self.h is not None:
            n = len(fresh)
            self._check(self.h.addCols(n, np.ones(n), np.zeros(n), np.full(n, np.inf),
                                      block.nnz, block.indptr.astype(np.int32),
                                      block.indices.astype(np.int32), block.data))
        # HiGHS appends, so with atoms present the new rectangle columns land
        # after them. Keep the cached matrix in that same order -- rectangles,
        # atoms, then later rectangles -- rather than assuming one contiguous
        # rectangle block, and remember where each rectangle's column sits.
        self.A = sparse.hstack([self.A, block], format='csr')
        self.rect_cols = np.r_[self.rect_cols,
                               np.arange(len(fresh)) + self.A.shape[1] - len(fresh)]
        self.rectangles = np.vstack([self.rectangles, fresh])
        self.rect_keys.update(keys)
        return len(fresh)

    def solve(self):
        if not len(self.poses):
            raise ValueError('At least one coverage constraint is required')
        start = perf_counter()
        if self.h is not None:
            import highspy
            self._check(self.h.run())
            status = self.h.getModelStatus()
            if status != highspy.HighsModelStatus.kOptimal:
                raise RuntimeError(f'Master not optimal: {status}. Infeasible support needs feasibility restoration.')
            sol, info = self.h.getSolution(), self.h.getInfo()
            weights, dual = np.asarray(sol.col_value), np.asarray(sol.row_dual)
            iterations = info.simplex_iteration_count
        else:
            ncols = self.A.shape[1]
            lo = np.zeros(ncols); hi = np.full(ncols, np.inf)
            if len(self.atoms):
                lo[self.atom_cols] = self.atom_lo
                hi[self.atom_cols] = self.atom_hi
            sol = linprog(np.ones(ncols), A_ub=-self.A,
                          b_ub=-np.full(len(self.poses), self.rhs),
                          bounds=list(zip(lo, hi)),
                          method='highs-ds', options={'dual_feasibility_tolerance': 1e-8,
                                                     'primal_feasibility_tolerance': 1e-8})
            if not sol.success:
                raise RuntimeError(f'Master not optimal: {sol.message}')
            weights, dual, iterations = sol.x, -sol.ineqlin.marginals, sol.nit
        raw_weights, raw_dual = weights.copy(), dual.copy()
        weights = np.maximum(weights, 0)
        dual = np.maximum(dual, 0)
        minimum = float(np.min(self.A@weights))
        # Simplex roundoff can leave coverage marginally short of rhs; rescale
        # weights uniformly to restore exact feasibility (mass only moves up).
        if 0 < minimum < self.rhs:
            weights = weights*(self.rhs/minimum)
            minimum = float(np.min(self.A@weights))
        # Both dual checks below only apply to columns the LP can actually
        # choose. A column pinned to a bound carries its reduced cost in the
        # bound multiplier instead of the row duals, so `A.T y <= c` does not
        # constrain it and its mass does not appear in `rhs * y.sum()`. Atoms
        # under atom_mode='fixed' are exactly such columns: restrict the
        # violation to the free columns and take their constant mass out of
        # the gap.
        free = np.ones(self.A.shape[1], bool)
        reduced = self.A.T@dual
        correction = 0.
        if len(self.atoms) and self.atom_mode == 'fixed':
            free[self.atom_cols] = False
            # Strong duality with bounds reads
            #     c.x == rhs*y.sum() + sum_j l_j*(c_j - (A.T y)_j)
            # over columns held at their lower bound l_j, the second term being
            # their bound multiplier. Unit costs make c_j = 1.
            correction = float((self.atom_lo*(1.-reduced[self.atom_cols])).sum())
        violation = float(max(0., np.max(reduced[free])-1)) if free.any() else 0.
        gap = float(weights.sum()-self.rhs*dual.sum()-correction)
        # Dual-side roundoff has no cheap exact fix like the primal rescale above;
        # observed noise on this engine's runs tops out around 1.2e-5 (violation)
        # and 3.8e-5 (gap), so these keep margin over that without going slack.
        if minimum < self.rhs-2e-7 or violation > 2e-5 or abs(gap) > 1e-4:
            error = RuntimeError(f'LP residual check failed: min={minimum}, dual={violation}, gap={gap}')
            try:
                capture = save_failure(self, raw_weights, raw_dual, weights, dual,
                                       dict(minimum=minimum, dual=violation, gap=gap,
                                            correction=correction), sol)
                error.add_note(f'LP failure saved: {capture}')
            except Exception as capture_error:
                error.add_note(f'LP failure capture also failed: {capture_error!r}')
            raise error
        return Solution(weights, dual, float(weights.sum()), perf_counter()-start,
                        int(iterations), minimum, violation, gap)

    def fingerprint(self):
        h = hashlib.sha256()
        for array in [np.array([self.L, self.B, self.rhs]), self.rectangles, self.poses]:
            h.update(np.asarray(array, dtype='<f8').tobytes())
        return h.hexdigest()

    def save_basis(self, path):
        basis = self.h.getBasis()
        path.write_text(json.dumps({'model_sha256': self.fingerprint(),
                                    'col_status': [int(x) for x in basis.col_status],
                                    'row_status': [int(x) for x in basis.row_status]}))

    def load_basis(self, path):
        import highspy
        data = json.loads(path.read_text())
        if (data['model_sha256'] != self.fingerprint()
                or len(data['col_status']) != len(self.rectangles)
                or len(data['row_status']) != len(self.poses)):
            raise ValueError('Saved basis belongs to a different LP')
        basis = highspy.HighsBasis()
        basis.col_status = [highspy.HighsBasisStatus(x) for x in data['col_status']]
        basis.row_status = [highspy.HighsBasisStatus(x) for x in data['row_status']]
        self._check(self.h.setBasis(basis))
