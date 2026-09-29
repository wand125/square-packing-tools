#!/usr/bin/env python3
"""Suggest the next ladder L from a certified rung, using the budget headroom it left.

A certified rung was scaled up from an LP solution of mass m0 to the budget n - 1/100.
If mass grew like L^2 the rung could have reached L_max = L * sqrt((n - 1/100) / m0).
This is a heuristic, not an attainable bound or an impossibility bound: B stays fixed,
and changing L changes intersection constraints and may require new supports.
The n52 observation (7.38 -> 7.40 kept m0 ~ 50.65) does not establish a general rate.
The legacy output name L_max_L2 denotes this estimate only. Do not exclude a parent
solely on this value. The suggestion goes half way from L to the estimate, rounded
down to 1/200, and never less than L + 1/400.

    python transfer/next_step.py <certificate dir with candidate.json or certified_candidate.json> [n]
"""
import json, sys
from fractions import Fraction as F
from math import sqrt, floor
from pathlib import Path

d = Path(sys.argv[1])
c = None
for name in ('certificate/certified_candidate.json', 'candidate.json', 'certified_candidate.json'):
    if (d / name).exists():
        c = json.loads((d / name).read_text()); break
if c is None: sys.exit('no candidate in ' + str(d))
n = int(sys.argv[2]) if len(sys.argv) > 2 else int(c['n'])
L = float(F(str(c['L']))); se = c.get('scaling_experiment') or {}
m0 = float(F(se['source_mass_exact'])) if se else float(F(str(c.get('mass', n - 0.01))))
b = n - 0.01
lmax = L * sqrt(b / m0)
nxt = max(L + 0.0025, floor((L + (lmax - L) / 2) * 200) / 200)
print(json.dumps(dict(n=n, L=L, unscaled_mass=round(m0, 4), budget=b, headroom=round(b - m0, 3),
                      L_max_L2=round(lmax, 4), suggested_next=f'{nxt:.4f}'.rstrip('0').rstrip('.'))))
