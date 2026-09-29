#!/usr/bin/env python3
"""Largest L a rectangle certificate for n can reach (L_cap), from the known upper bound UB(n).

    python transfer/l_cap.py 29 [30 ...]

UB(n) comes from data/ub.json (see its `_source` field).
"""
import json
import math
import sys
from pathlib import Path

CORE_B = 0.9977   # the verifier's core side
UB = {r['n']: r['ub'] for r in json.loads((Path(__file__).resolve().parent / 'data/ub.json').read_text())['rows'] if r.get('ub')}


def L_cap(n):
    """Largest L a rectangle certificate for n can reach: below B*UB(n). UB(n) is the side of a known packing of
    n unit squares; at L >= B*UB(n) the packing shrunk by B fits, its n disjoint cores each need coverage >= 1,
    so every measure has mass >= n > n - 0.01 (observed: n61 at L7.99 needed 64 x 1.001,
    n77/78 at 8.985-8.995 needed 81 x 1.001). Returns None when no upper bound is known."""
    ub = UB.get(n)
    return math.floor(CORE_B * ub * 1000 - 1e-6) / 1000 if ub else None


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    for text in argv:
        n = int(text)
        print(json.dumps(dict(n=n, UB=UB.get(n), B=CORE_B, L_cap=L_cap(n))))


if __name__ == '__main__':
    main(sys.argv[1:])
