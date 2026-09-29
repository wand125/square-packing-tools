"""Run with the selected rectangle engine on PYTHONPATH."""
import unittest
from types import SimpleNamespace
import numpy as np
from geometry import Geometry, rectangle_key
from edge_pricing import propose_edges


class PricingTests(unittest.TestCase):
    def setUp(self):
        r = np.array([[.2, .4, .8, 1.1], [1., .6, 1.2, 1.7]])
        poses = np.random.default_rng(37).uniform(0, 1, (40, 3))
        self.m = SimpleNamespace(L=4.7, B=.9977, rectangles=r,
            poses=poses, rect_cols=np.arange(2), atoms=[],
            rect_keys={rectangle_key(x, 4.7) for x in r})
        self.s = SimpleNamespace(weights=np.array([1., .8]),
                                  dual=np.linspace(0, 5, 40))

    def test_geometry_score_and_preservation(self):
        rectangles = self.m.rectangles.copy()
        poses = self.m.poses.copy()
        columns, report = propose_edges(self.m, self.s, seed_count=2,
            local_starts=2, max_evaluations=30, max_columns=8)
        self.assertTrue(columns)
        self.assertLessEqual(len(columns), 8)
        r = np.array([c['rectangle'] for c in columns])
        self.assertTrue(np.all(r[:, :2] >= .001))
        self.assertTrue(np.all(r[:, 2:] <= 4.7-.001))
        self.assertTrue(np.all(r[:, 2:]-r[:, :2] >= .001))
        # Independent full-row rescore, including zero dual rows.
        actual = self.s.dual @ Geometry(4.7, .9977, r).matrix(poses)
        np.testing.assert_allclose(actual, [c['score'] for c in columns],
                                   rtol=1e-12, atol=1e-12)
        self.assertTrue(np.all(actual > 1+1e-6))
        self.assertEqual(len({rectangle_key(x, 4.7) for x in r}), len(r))
        self.assertTrue(all(rectangle_key(x, 4.7) not in self.m.rect_keys for x in r))
        np.testing.assert_array_equal(rectangles, self.m.rectangles)
        np.testing.assert_array_equal(poses, self.m.poses)
        self.assertEqual(report['status'], 'HEURISTIC_PRICING')

    def test_zero_dual_does_not_invent_improvement(self):
        self.s.dual[:] = 0
        columns, _ = propose_edges(self.m, self.s, local_starts=0)
        self.assertEqual(columns, [])

    def test_rejects_invalid_dual_and_atoms(self):
        with self.assertRaises(ValueError):
            propose_edges(self.m, self.s, margin=0.)
        with self.assertRaises(ValueError):
            propose_edges(self.m, self.s, min_side=-1.)
        self.s.dual[1] = -1
        with self.assertRaises(ValueError):
            propose_edges(self.m, self.s)
        self.s.dual[1] = 0
        self.m.atoms = [[0, 0]]
        with self.assertRaises(ValueError):
            propose_edges(self.m, self.s)

    def test_boundary_candidates_keep_smoothing_margin(self):
        self.m.rectangles = np.array([[.001, .001, .8, 1.1],
                                     [3.5, 3.7, 4.699, 4.699]])
        self.m.rect_keys = {rectangle_key(r, 4.7) for r in self.m.rectangles}
        columns, _ = propose_edges(self.m, self.s, seed_count=2,
                                    local_starts=2, max_evaluations=30)
        for column in columns:
            r = np.asarray(column['rectangle'])
            self.assertTrue(np.all(r[:2] > 1/20000))
            self.assertTrue(np.all(r[2:] < 4.7-1/20000))


if __name__ == '__main__':
    unittest.main()
