"""Exact parent enclosure for an angle row (generalizes PL30/PL43/PL48).

Setting: a parent is a side-A square in [0,L]^2 whose orientation is
theta(u) = 2*arctan(u) with half-angle u in [a,b] subset [0,1).  Rational
half-angle coordinates c(u) = (1-u^2)/(1+u^2), s(u) = 2u/(1+u^2).

1. Centre domain.  A parent at orientation theta(u) in [0,pi/2) has
   axis-aligned half-extent A*(c(u)+s(u))/2, so its centre lies in
   [A f(u)/2, L - A f(u)/2]^2 with f = c+s.  The union over u in [a,b] is the
   square [r, L-r]^2 with r = A*min_{[a,b]} f / 2.
   f'(u) = -2 g(u) / (1+u^2)^2 with g(u) = u^2 + 2u - 1.  For u >= 0,
   g'(u) = 2u + 2 > 0, so g is strictly increasing and changes sign at most
   once (from - to +).  Hence f' changes sign at most once, from + to -:
   f is increasing-then-decreasing (quasi-concave) on [a,b] and its minimum
   over [a,b] is attained at an endpoint.  We check a >= 0 exactly (the only
   hypothesis used) and take r = A*min(f(a), f(b))/2.

2. Strict core containment.  The row assigns a concentric closed core of side
   B at orientation theta(t).  Relative angle delta(u) = theta(u) - theta(t)
   has cos delta = c(t)c(u) + s(t)s(u), sin delta = c(t)s(u) - s(t)c(u)
   (exact rationals).  A concentric square of side B at relative angle delta
   has half-extent B*(|cos delta| + |sin delta|)/2 along each parent axis, so
   it lies strictly inside the parent iff A > B*(|cos delta| + |sin delta|).
   delta(u) is continuous and strictly increasing in u, so over [a,b] it
   sweeps the interval [delta(a), delta(b)].  If both endpoints satisfy
   cos delta > 0 and cos delta >= |sin delta| (i.e. |delta| <= pi/4) the
   whole interval lies in [-pi/4, pi/4]; there w(delta) = cos delta + |sin delta|
   = sqrt(2) cos(pi/4 - |delta|) is increasing in |delta|, and |delta| over an
   interval is maximal at an endpoint.  So checking A > B*w at u = a and u = b
   proves strict containment for every u in [a,b].

3. Coverage.  Rows must satisfy a_0 = 0, a_{i+1} = b_i, a_i < b_i, and the last
   b satisfies b^2 + 2b > 1, i.e. b > sqrt(2) - 1 (theta(b) > pi/4).
"""
from fractions import Fraction as F


def trig(t):
    t = F(t)
    return (1 - t * t) / (1 + t * t), 2 * t / (1 + t * t)


def f_width(u):
    c, s = trig(u)
    return c + s


def centre_radius(A, a, b):
    """Exact r with centre domain [r, L-r]^2 for half-angles in [a,b]."""
    A, a, b = F(A), F(a), F(b)
    if not (0 <= a <= b < 1):
        raise ValueError("need 0 <= a <= b < 1")
    # g(u) = u^2+2u-1 is strictly increasing on u >= 0 (g' = 2u+2 > 0): f' has at
    # most one sign change, from + to -, so no interior minimum of f on [a,b].
    ga, gb = a * a + 2 * a - 1, b * b + 2 * b - 1
    assert ga <= gb  # monotone, sanity
    return A * min(f_width(a), f_width(b)) / 2


def core_margin(A, B, a, b, t):
    """Return A - B*max_{u in {a,b}} (cos delta + |sin delta|) after checking
    |delta| <= pi/4 at both endpoints.  Positive result => strict containment
    for every u in [a,b] (see module docstring)."""
    A, B = F(A), F(B)
    ct, st = trig(t)
    widths = []
    for u in (F(a), F(b)):
        cu, su = trig(u)
        cosd = ct * cu + st * su
        sind = ct * su - st * cu
        if not (cosd > 0 and cosd >= abs(sind)):
            raise ValueError(f"relative angle outside [-pi/4,pi/4] at u={u}")
        widths.append(cosd + abs(sind))
    return A - B * max(widths)


def check_rows(rows, L, A):
    """Check a catalogue of rows (a,b,t,B).  Returns a summary dict; raises on failure."""
    L, A = F(L), F(A)
    cursor = F(0)
    min_margin = None
    radii = []
    for i, row in enumerate(rows):
        a, b, t, B = map(F, row)
        if a != cursor or not (0 <= a < b < 1) or not (0 <= t < 1) or not (0 < B < A):
            raise ValueError(f"coverage/format failure at row {i}")
        m = core_margin(A, B, a, b, t)
        if m <= 0:
            raise ValueError(f"core not strictly inside parent at row {i}")
        r = centre_radius(A, a, b)
        if not (0 < r < L / 2):
            raise ValueError(f"empty centre domain at row {i}")
        radii.append(r)
        min_margin = m if min_margin is None else min(min_margin, m)
        cursor = b
    if not cursor * cursor + 2 * cursor > 1:
        raise ValueError("rows do not reach sqrt(2)-1")
    return dict(rows=len(rows), last_b=str(cursor), reaches_sqrt2_minus_1=True,
                min_core_margin=str(min_margin), min_radius=str(min(radii)), max_radius=str(max(radii)),
                contiguous_from_zero=True)


if __name__ == "__main__":
    import json, sys, time
    c = json.load(open(sys.argv[1]))
    t0 = time.monotonic()
    out = check_rows(c["entries"], c["L"], c["A"])
    out["seconds"] = time.monotonic() - t0
    print(json.dumps(out, indent=2))
    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(json.dumps(out, indent=2) + "\n")
