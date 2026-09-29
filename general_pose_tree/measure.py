"""Generic charge measures for square-packing charge certificates.

A measure lives on the container [0,L]^2 and consists of

* sites: exact rational points, stored as integer pairs (X, Y) with a common
  coordinate denominator D (site = (X/D, Y/D));
* ordinary weights: integer weight w_i >= 0 on site i (budget w_i);
* threshold features: (sites, k, w) meaning "charge w if a closed core contains
  at least k of these m distinct sites" (budget floor(m/k) * w).

Weights are integers in units of 1/weight_denominator.  All arithmetic here is
exact (Python ints / Fractions).  The budget argument (pigeonhole over pairwise
disjoint closed cores) is the one stated in Kleddamag's PROOF.md; this module
only computes the numbers.
"""
from fractions import Fraction as F
from itertools import combinations
from math import comb
import json


class Feature:
    __slots__ = ("sites", "k", "w")

    def __init__(self, sites, k, w):
        sites = tuple(sites)
        if len(set(sites)) != len(sites):
            raise ValueError("feature sites must be distinct")
        if not (isinstance(k, int) and 1 <= k <= len(sites)):
            raise ValueError("invalid threshold")
        if not (isinstance(w, int) and w >= 0):
            raise ValueError("invalid feature weight")
        self.sites, self.k, self.w = sites, k, w

    @property
    def budget(self):
        return (len(self.sites) // self.k) * self.w

    def __repr__(self):
        return f"Feature({self.sites},k={self.k},w={self.w})"


class Measure:
    """Ordinary weighted points plus k-of-m threshold features."""

    def __init__(self, coords, weights, features=(), D=1, weight_denominator=1):
        if len(coords) != len(weights):
            raise ValueError("coords/weights length mismatch")
        if len(set(map(tuple, coords))) != len(coords):
            raise ValueError("duplicate sites")
        if any((not isinstance(w, int)) or w < 0 for w in weights):
            raise ValueError("ordinary weights must be nonnegative integers")
        self.coords = [tuple(map(int, c)) for c in coords]
        self.weights = list(weights)
        self.features = [f for f in features if f.w > 0]
        for f in self.features:
            if any(not (0 <= i < len(coords)) for i in f.sites):
                raise ValueError("feature site index out of range")
        self.D = D
        self.weight_denominator = weight_denominator

    # ------------------------------------------------------------------ budget
    def budget(self):
        """Exact total budget M (integer units)."""
        return sum(self.weights) + sum(f.budget for f in self.features)

    def relevant_sites(self):
        """Sites that can change the charge (positive ordinary weight or in a positive feature)."""
        s = {i for i, w in enumerate(self.weights) if w > 0}
        for f in self.features:
            s.update(f.sites)
        return sorted(s)

    # --------------------------------------------------------------- evaluation
    def charge_of_set(self, captured):
        """Charge of a core that captures exactly the site-index set `captured`."""
        captured = set(captured)
        total = sum(self.weights[i] for i in captured)
        for f in self.features:
            if sum(1 for i in f.sites if i in captured) >= f.k:
                total += f.w
        return total

    def charge_of_set_signed(self, captured):
        """Independent evaluation through the signed inclusion-exclusion identity
        1[sum x >= k] = sum_{j>=k} (-1)^(j-k) C(j-1,k-1) sum_{|S|=j} prod x_S
        (used only as a cross-check in tests)."""
        captured = set(captured)
        total = sum(self.weights[i] for i in captured)
        for f in self.features:
            for j in range(f.k, len(f.sites) + 1):
                coef = (-1) ** (j - f.k) * comb(j - 1, f.k - 1) * f.w
                for part in combinations(f.sites, j):
                    if all(i in captured for i in part):
                        total += coef
        return total

    def captured(self, cx, cy, B, t):
        """Indices of sites in the closed side-B square centred (cx,cy) at angle 2*arctan(t).
        Direct exact membership test (no shared code with branch.py)."""
        cx, cy, B, t = F(cx), F(cy), F(B), F(t)
        c, s = (1 - t * t) / (1 + t * t), 2 * t / (1 + t * t)
        half = B / 2
        out = []
        for i, (X, Y) in enumerate(self.coords):
            dx, dy = F(X, self.D) - cx, F(Y, self.D) - cy
            if abs(c * dx + s * dy) <= half and abs(-s * dx + c * dy) <= half:
                out.append(i)
        return out

    def charge_at(self, cx, cy, B, t):
        return self.charge_of_set(self.captured(cx, cy, B, t))

    # ------------------------------------------------------------ D4 symmetry
    def d4_images(self, span):
        """Yield the 8 maps (X,Y)->(X',Y') of the D4 group of [0,span]^2 (integer coords)."""
        for swap in (False, True):
            for sx in (False, True):
                for sy in (False, True):
                    def g(p, swap=swap, sx=sx, sy=sy):
                        x, y = p
                        if swap:
                            x, y = y, x
                        if sx:
                            x = span - x
                        if sy:
                            y = span - y
                        return (x, y)
                    yield g

    def check_d4(self, L):
        """Exact check that ordinary weights and the multiset of features are D4 invariant."""
        span = F(L) * self.D
        if span.denominator != 1:
            raise ValueError("L*D must be an integer")
        span = int(span)
        lookup = {p: i for i, p in enumerate(self.coords)}
        feats = {}
        for f in self.features:
            key = (frozenset(f.sites), f.k, f.w)
            feats[key] = feats.get(key, 0) + 1
        for g in self.d4_images(span):
            for i, p in enumerate(self.coords):
                q = g(p)
                if self.weights[i] > 0 and (q not in lookup or self.weights[lookup[q]] != self.weights[i]):
                    return False
            img = {}
            for f in self.features:
                try:
                    key = (frozenset(lookup[g(self.coords[i])] for i in f.sites), f.k, f.w)
                except KeyError:
                    return False
                img[key] = img.get(key, 0) + 1
            if img != feats:
                return False
        return True


def load_kleddamag(path):
    """Load Kleddamag's global-certificate.json.

    Site expansion replicates exact_mixed.expand(): for each point orbit
    [x,y,w] (in order) append sorted({(a,b) for (u,v) in [(x,y),(y,x)]
    for a in (u,LD-u) for b in (v,LD-v)}); charge_orbits 'sets' index into
    that list.  Returns (measure, raw_json_dict).
    """
    with open(path) as fh:
        c = json.load(fh)
    D = c["coordinate_denominator"]
    L = F(c["L"])
    LD = L * D
    assert LD.denominator == 1
    LD = int(LD)
    coords, weights = [], []
    for x, y, w in c["point_orbits"]:
        assert all(isinstance(v, int) for v in (x, y, w)) and 0 <= x <= LD and 0 <= y <= LD and w >= 0
        orbit = sorted({(a, b) for u, v in [(x, y), (y, x)] for a in (u, LD - u) for b in (v, LD - v)})
        coords += orbit
        weights += [w] * len(orbit)
    features = []
    for atom in c["charge_orbits"]:
        for s in atom["sets"]:
            features.append(Feature(s, atom["threshold"], atom["weight"]))
    m = Measure(coords, weights, features, D=D, weight_denominator=c["weight_denominator"])
    return m, c


def kleddamag_orbit_check(measure, c):
    """Check every charge orbit's 'sets' is exactly the D4 orbit of its first set."""
    D = measure.D
    span = int(F(c["L"]) * D)
    lookup = {p: i for i, p in enumerate(measure.coords)}
    for atom in c["charge_orbits"]:
        groups = atom["sets"]
        orbit = set()
        for g in measure.d4_images(span):
            orbit.add(frozenset(lookup[g(measure.coords[i])] for i in groups[0]))
        if orbit != set(frozenset(s) for s in groups) or len(orbit) != len(groups):
            return False
    return True


if __name__ == "__main__":
    import sys
    m, c = load_kleddamag(sys.argv[1])
    fam = {}
    for f in m.features:
        key = f"{f.k}-of-{len(f.sites)}"
        n, b = fam.get(key, (0, 0))
        fam[key] = (n + 1, b + f.budget)
    print("sites", len(m.coords), "positive ordinary", sum(1 for w in m.weights if w > 0))
    print("families", fam)
    print("budget", m.budget(), "expected", c["budget_units"], m.budget() == c["budget_units"])
    print("D4", m.check_d4(F(c["L"])), "orbit sets", kleddamag_orbit_check(m, c))
