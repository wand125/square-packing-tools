import unittest
from types import SimpleNamespace
import numpy as np
from scipy.sparse import csr_matrix, vstack, hstack
from scipy.optimize import linprog
from master import Master
from working_rows import solve_working_rows, seed_dual


class WorkingRowsTests(unittest.TestCase):
    def model(self):
        A=np.random.default_rng(126).uniform(.02,1,(60,12))
        A[0]=1.
        return SimpleNamespace(A=csr_matrix(A),poses=np.zeros((60,3)),atoms=[],rhs=1.001,_check=Master._check)

    def test_omitted_violations_are_added_and_full_optimum_matches(self):
        m=self.model();dual=np.zeros(60);dual[0]=1
        result, report=solve_working_rows(m,dual,batch=3)
        full=linprog(np.ones(12),A_ub=-m.A,b_ub=-np.full(60,m.rhs),bounds=(0,None),method='highs')
        self.assertTrue(full.success)
        self.assertGreater(report['rounds'],1)
        self.assertAlmostEqual(result.mass,full.fun,places=6)
        self.assertGreaterEqual(float((m.A@result.weights).min()),m.rhs-2e-7)
        self.assertLessEqual(float((m.A.T@result.dual).max()),1+2e-5)

    def test_incomplete_working_model_is_never_accepted(self):
        m=self.model();dual=np.zeros(60);dual[0]=1
        with self.assertRaisesRegex(RuntimeError,'review limit'):
            solve_working_rows(m,dual,batch=1,max_rounds=1)

    def test_invalid_dual_rejected(self):
        with self.assertRaises(ValueError):solve_working_rows(self.model(),np.full(60,-1.))

    def test_reuse_adds_new_violations_and_matches_cold_model(self):
        m = self.model()
        first, _ = solve_working_rows(m, np.ones(60), reuse=True)
        # New row makes the previous optimum infeasible.
        m.A = vstack([m.A, csr_matrix(np.full((1, 12), .03))], format='csr')
        m.poses = np.zeros((61, 3))
        hint = np.r_[first.dual, 0.]
        warm, report = solve_working_rows(m, hint, reuse=True)
        cold, _ = solve_working_rows(m, hint)
        self.assertTrue(report['reused_solver'])
        self.assertGreater(report['rounds'], 1)
        self.assertAlmostEqual(warm.mass, cold.mass, places=6)
        self.assertGreaterEqual(float((m.A @ warm.weights).min()), m.rhs-2e-7)

    def test_changed_model_invalidates_reuse(self):
        for change in ('coefficient', 'rhs', 'column', 'removed_row', 'row_order'):
            with self.subTest(change=change):
                m = self.model()
                solve_working_rows(m, np.ones(60), reuse=True)
                if change == 'coefficient': m.A.data[0] *= .8
                if change == 'rhs': m.rhs += .01
                if change == 'column': m.A = hstack([m.A, m.A[:, :1]], format='csr')
                if change == 'removed_row': m.A = m.A[:-1]; m.poses = m.poses[:-1]
                if change == 'row_order': m.A = m.A[np.arange(60)[::-1]]
                warm, report = solve_working_rows(m, np.ones(len(m.poses)), reuse=True)
                cold, _ = solve_working_rows(m, np.ones(len(m.poses)))
                self.assertFalse(report['reused_solver'])
                self.assertAlmostEqual(warm.mass, cold.mass, places=6)

    def test_failed_reuse_discards_partial_solver(self):
        m = self.model()
        first, _ = solve_working_rows(m, np.ones(60), reuse=True)
        m.A = vstack([m.A, csr_matrix(np.full((1, 12), .03))], format='csr')
        m.poses = np.zeros((61, 3))
        with self.assertRaisesRegex(RuntimeError, 'review limit'):
            solve_working_rows(m, np.r_[first.dual, 0.], reuse=True, max_rounds=1)
        self.assertFalse(hasattr(m, '_working_rows_cache'))

    def test_large_working_set_returns_to_cold_initialization(self):
        m = self.model()
        # Repeated constraints give a deliberately oversized but valid working set.
        m.A = vstack([m.A]*70, format='csr'); m.poses = np.zeros((4200, 3))
        first, report = solve_working_rows(m, np.ones(4200), reuse=True)
        self.assertEqual(report['working_rows'], 4200)
        second, report = solve_working_rows(m, first.dual, reuse=True)
        self.assertFalse(report['reused_solver'])
        self.assertAlmostEqual(first.mass, second.mass, places=6)

    def test_saved_dual_extends_only_matching_model_prefix(self):
        m = self.model()
        m.L, m.B = 3.96, .9977
        m.poses = np.arange(180).reshape(60, 3)
        m.rectangles = np.arange(48).reshape(12, 4)
        saved = dict(L=m.L, B=m.B, rhs=m.rhs, poses=m.poses[:10].copy(),
                     rectangles=m.rectangles[:4].copy(), dual=np.ones(10))
        initial = seed_dual(m, saved)
        np.testing.assert_array_equal(initial, np.r_[np.ones(10), np.zeros(50)])
        # Even a mapped seed cannot bypass omitted-row feasibility checks.
        result, _ = solve_working_rows(m, initial, batch=3)
        self.assertGreaterEqual(float((m.A @ result.weights).min()), m.rhs-2e-7)
        saved['poses'] = saved['poses'][::-1]
        with self.assertRaises(ValueError): seed_dual(m, saved)

if __name__=='__main__':unittest.main()
