#!/usr/bin/env python3
"""Search ceiling for L (L_cap): a guide to where a rectangle certificate for n stops being possible.

    python transfer/l_cap.py 29 [30 ...]

UB(n) comes from data/ub.json (see its `_source` field). Those values are rounded for display,
so L_cap is a guide for choosing search targets, not a proven bound.
"""
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

CORE_B = Fraction(9977, 10000)   # the verifier's core side B
NET_D = Fraction(83, 40000)      # the verifier's net parameter D (certificate metadata "D")
ALPHA = CORE_B * (1 + NET_D)     # = 399908091/400000000
ROWS = {r['n']: r for r in json.loads((Path(__file__).resolve().parent / 'data/ub.json').read_text())['rows'] if r.get('ub')}
UB = {n: r['ub'] for n, r in ROWS.items()}


def on_net(n):
    """True when the known packing is a k x k axis-parallel grid subset (integer UB): orientation 0
    is an angle of the verifier's net, so the sharper factor B applies."""
    r = ROWS.get(n)
    return bool(r) and float(r['ub']).is_integer() and r.get('ubExact') == str(int(r['ub']))


def factor(n):
    return CORE_B if on_net(n) else ALPHA


def L_cap(n):
    """Search ceiling B*UB(n) for an integer UB (axis-parallel grid packing), alpha*UB(n) otherwise,
    rounded down to 1/1000; None when no upper bound is known.

    UB(n) is the side of a known packing of n unit squares. If that packing, shrunk by B, fits in
    the box *and* every square's orientation lies on the verifier's 201-angle net, its n disjoint
    cores each need coverage >= 1, so every measure has mass >= n and the budget n - 1/100 cannot
    be met: the ceiling would be B*UB(n). For a general orientation the angle-net slack costs a
    further factor (1 + D), giving alpha*UB(n) with alpha = B(1 + 83/40000) = 399908091/400000000.
    An integer UB(n) = k comes from a k x k axis-parallel grid, whose orientation 0 is on the net,
    so B*k is used there (alpha would loosen e.g. n = 72..81 from 8.979 to 8.997).
    Because UB(n) in data/ub.json is rounded, treat the result as a guide for the search, not
    as a proven bound. (Observed: n61 at L 7.99 needed 64 x 1.001; n77/78 at 8.985-8.995
    needed 81 x 1.001.)"""
    ub = UB.get(n)
    return math.floor(float(factor(n)) * ub * 1000 - 1e-6) / 1000 if ub else None


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    for text in argv:
        n = int(text)
        print(json.dumps(dict(n=n, UB=UB.get(n), alpha=str(ALPHA), factor=str(factor(n)) if n in UB else None, L_cap=L_cap(n), note='search guide, not a proven bound')))


if __name__ == '__main__':
    main(sys.argv[1:])
