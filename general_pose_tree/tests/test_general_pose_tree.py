"""Brute-force tests for measure.py, enclosure.py and branch.py.

Run:  python -m pytest -q tests/
"""
import random
import sys
from fractions import Fraction as F
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from measure import Measure, Feature  # noqa: E402
from enclosure import centre_radius, core_margin, check_rows, trig  # noqa: E402
from branch import RowSolver, brute_min  # noqa: E402


def random_measure(rng, n_sites=18, span=40, D=10, n_feat=6, d4=False):
    """Random measure on [0, span/D]^2 with integer coordinates in [0, span]."""
    pts = set()
    while len(pts) < n_sites:
        x, y = rng.randint(0, span), rng.randint(0, span)
        if d4:
            for u, v in [(x, y), (y, x)]:
                for a in (u, span - u):
                    for b in (v, span - v):
                        pts.add((a, b))
        else:
            pts.add((x, y))
    coords = sorted(pts)
    weights = [rng.choice([0, 0, 1, 2, 5]) for _ in coords]
    feats = []
    for _ in range(n_feat):
        m = rng.choice([2, 3, 5])
        if m > len(coords):
            continue
        k = rng.randint(1, m)
        feats.append(Feature(rng.sample(range(len(coords)), m), k, rng.randint(1, 7)))
    return Measure(coords, weights, feats, D=D)


def rand_centre(rng, lo, hi, den=997):
    return lo + (hi - lo) * F(rng.randint(1, den - 1), den)


# ---------------------------------------------------------------- measure
def test_charge_threshold_vs_signed_expansion():
    rng = random.Random(1)
    for _ in range(30):
        m = random_measure(rng)
        for _ in range(40):
            cap = [i for i in range(len(m.coords)) if rng.random() < 0.4]
            assert m.charge_of_set(cap) == m.charge_of_set_signed(cap)


def test_budget_pigeonhole_on_disjoint_assignments():
    """For random disjoint partitions of sites into cores, total charge <= budget."""
    rng = random.Random(2)
    for _ in range(50):
        m = random_measure(rng, n_sites=10, n_feat=8)
        for _ in range(50):
            q = rng.randint(1, 6)
            label = [rng.randint(-1, q - 1) for _ in m.coords]
            total = sum(m.charge_of_set([i for i, l in enumerate(label) if l == j]) for j in range(q))
            assert total <= m.budget()


def test_d4_check():
    rng = random.Random(3)
    m = random_measure(rng, n_sites=8, d4=True, n_feat=0)
    # make weights orbit-constant: weight = function of sorted |centred| coordinates
    span = 40
    key = lambda p: tuple(sorted((min(p[0], span - p[0]), min(p[1], span - p[1]))))
    m.weights = [1 + sum(key(p)) % 3 for p in m.coords]
    assert m.check_d4(F(span, 10))
    m.weights[0] += 1
    assert not m.check_d4(F(span, 10))


# ---------------------------------------------------------------- enclosure
def test_centre_radius_endpoint_min_by_sampling():
    rng = random.Random(4)
    for _ in range(200):
        a = F(rng.randint(0, 900), 1000)
        b = a + F(rng.randint(1, 99), 1000)
        r = centre_radius(1, a, b)
        for j in range(21):
            u = a + (b - a) * F(j, 20)
            c, s = trig(u)
            assert (c + s) / 2 >= r


def test_core_margin_by_sampling():
    rng = random.Random(5)
    for _ in range(200):
        a = F(rng.randint(0, 400), 1000)
        b = a + F(rng.randint(1, 20), 1000)
        t = a + (b - a) * F(rng.randint(0, 10), 10)
        A = F(1)
        B = F(rng.randint(900, 999), 1000)
        mg = core_margin(A, B, a, b, t)
        ct, st = trig(t)
        for j in range(11):
            u = a + (b - a) * F(j, 10)
            cu, su = trig(u)
            w = abs(ct * cu + st * su) + abs(ct * su - st * cu)
            assert A - B * w >= mg


def test_check_rows_rejects_gap():
    rows = [["0", "1/10", "1/20", "1/2"], ["1/10", "43/100", "1/4", "1/2"]]
    check_rows(rows, 4, 1)
    try:
        check_rows([rows[0], ["11/100", "43/100", "1/4", "1/2"]], 4, 1)
        assert False
    except ValueError:
        pass


# ---------------------------------------------------------------- branch
def test_classification_soundness():
    rng = random.Random(6)
    for _ in range(20):
        m = random_measure(rng, n_sites=25)
        L = F(4)
        t = F(rng.randint(0, 40), 100)
        B = F(rng.randint(70, 100), 100)
        r = centre_radius(1, t, t)
        s = RowSolver(m, L, B, t, r)
        for _ in range(30):
            U0 = rng.randint(s.PU0, s.PU1 - 2)
            U1 = rng.randint(U0 + 1, min(s.PU1, U0 + (s.PU1 - s.PU0) // 3 + 2))
            V0 = rng.randint(s.PV0, s.PV1 - 2)
            V1 = rng.randint(V0 + 1, min(s.PV1, V0 + (s.PV1 - s.PV0) // 3 + 2))
            cls = [s.classify(i, U0, U1, V0, V1) for i in range(len(s.ulo))]
            for _ in range(10):
                U = rand_centre(rng, U0, U1)
                V = rand_centre(rng, V0, V1)
                k = s.Q * s.R * s.R
                x, y = (s.C * U - s.S * V) / k, (s.S * U + s.C * V) / k
                cap = set(m.captured(x, y, B, t))
                for i, c in enumerate(cls):
                    g = s.global_index[i]
                    if c == 1:
                        assert g in cap
                    elif c == 0:
                        assert g not in cap


def test_meets_domain_vs_sampling():
    """If a random interior point of the box lies in the open domain, meets_domain must be True."""
    rng = random.Random(7)
    m = random_measure(rng, n_sites=5)
    for _ in range(10):
        t = F(rng.randint(0, 45), 100)
        s = RowSolver(m, 4, F(9, 10), t, centre_radius(1, t, t))
        k = s.Q * s.R * s.R
        for _ in range(100):
            w = (s.PU1 - s.PU0)
            U0 = rng.randint(s.PU0 - w // 4, s.PU1)
            V0 = rng.randint(s.PV0 - w // 4, s.PV1)
            U1, V1 = U0 + rng.randint(1, w // 3), V0 + rng.randint(1, w // 3)
            hit = False
            for _ in range(20):
                U, V = rand_centre(rng, U0, U1), rand_centre(rng, V0, V1)
                x, y = (s.C * U - s.S * V) / k, (s.S * U + s.C * V) / k
                if s.r < x < 4 - s.r and s.r < y < 4 - s.r:
                    hit = True
            if hit:
                assert s.meets_domain(U0, U1, V0, V1)


def test_exact_min_matches_brute_force_and_sampling():
    rng = random.Random(8)
    for trial in range(40):
        m = random_measure(rng, n_sites=rng.randint(6, 30), n_feat=rng.randint(0, 10))
        L = F(4)
        t = F(rng.randint(0, 45), 100)
        B = F(rng.randint(60, 100), 100)
        a = t
        r = centre_radius(F(1), a, a + F(1, 100))
        s = RowSolver(m, L, B, t, r)
        leaf = rng.choice([0, 2, 5, 10])
        res = s.minimize(leaf_size=leaf)
        assert res["minimum"] == brute_min(s)
        cert_ok = s.certify(res["minimum"], leaf_size=leaf)
        assert cert_ok["ok"]
        cert_bad = s.certify(res["minimum"] + 1, leaf_size=leaf)
        assert not cert_bad["ok"] and cert_bad["value"] == res["minimum"]
        # random centres in the closed domain never go below the minimum
        for _ in range(30):
            x, y = rand_centre(rng, r, L - r, 13), rand_centre(rng, r, L - r, 13)
            assert m.charge_at(x, y, B, t) >= res["minimum"]
        # domain corners / boundary points too (upper semicontinuity)
        for x, y in [(r, r), (L - r, r), (r, L - r), (L - r, L - r), (r, L / 2)]:
            assert m.charge_at(x, y, B, t) >= res["minimum"]


def test_point_measure_vs_exact_fixed_angle_separator():
    """Pure point measure, A=B=1: compare with PL37 separate() on random D4 inputs.

    Needs SP_BOUNDS_REPO = a checkout of wand125/square-packing-bounds; skipped otherwise."""
    import os
    import pytest
    if not os.environ.get("SP_BOUNDS_REPO"):
        pytest.skip("set SP_BOUNDS_REPO to a square-packing-bounds checkout")
    src = Path(os.environ["SP_BOUNDS_REPO"]) / "point_n21_L5/verifier-source/src/nagamochi_research"
    sys.path.insert(0, str(src))
    try:
        from exact_fixed_angle_separator import separate
    except Exception:  # pragma: no cover
        import pytest
        pytest.skip("separator unavailable")
    rng = random.Random(9)
    for _ in range(15):
        span, D = 40, 10
        m = random_measure(rng, n_sites=20, span=span, D=D, n_feat=0)
        L = F(span, D)
        t = F(rng.randint(0, 50), 100)
        pts = [(x, y, w) for (x, y), w in zip(m.coords, m.weights)]
        ref = separate(L, D, pts, t)["minimum_numerator"]
        c, s_ = trig(t)
        s = RowSolver(m, L, 1, t, (c + s_) / 2)
        assert s.minimize()["minimum"] == ref
