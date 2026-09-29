"""Cross-check branch.py against the PL37 exact fixed-angle separator on the n=21 point cover.

Point measure only, parent = core = side 1, L = 5, fixed angles t; centre domain
[h, L-h]^2 with h = (c(t)+s(t))/2 (identical to separate()).

    python check_n21.py <square-packing-bounds checkout> <out.json> <t> [<t> ...]

The separator and the n = 21 cover are read from a checkout of
https://github.com/wand125/square-packing-bounds (point_n21_L5/).
"""
import json
import sys
import time
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if len(sys.argv) < 4:
    raise SystemExit(__doc__)
BOUNDS = Path(sys.argv[1]).resolve() / "point_n21_L5"
sys.path.insert(0, str(BOUNDS / "verifier-source/src/nagamochi_research"))
from probe_external_integer_bridge import read  # noqa: E402
from exact_fixed_angle_separator import separate  # noqa: E402
from measure import Measure  # noqa: E402
from branch import RowSolver  # noqa: E402
from enclosure import trig  # noqa: E402

COVER = BOUNDS / "certificates/n21-original.txt"


def main(angles, out):
    L, span, W, pts = read(COVER)
    D = int(F(span) / L)
    agg = {}
    for x, y, w in pts:
        agg[x, y] = agg.get((x, y), 0) + w
    coords = sorted(agg)
    m = Measure(coords, [agg[p] for p in coords], (), D=D, weight_denominator=W)
    assert m.check_d4(L)
    recs = []
    for t in map(F, angles):
        t0 = time.monotonic()
        ref = separate(L, D, pts, t)
        t1 = time.monotonic()
        c, s = trig(t)
        res = RowSolver(m, L, 1, t, (c + s) / 2).minimize()
        t2 = time.monotonic()
        rec = dict(t=str(t), separator_minimum_numerator=ref["minimum_numerator"], branch_minimum=res["minimum"],
                   agree=ref["minimum_numerator"] == res["minimum"], separator_seconds=t1 - t0,
                   branch_seconds=t2 - t1, **{k: res[k] for k in ("boxes_expanded", "leaves", "max_depth", "cells")})
        print(json.dumps(rec), flush=True)
        recs.append(rec)
    Path(out).write_text(json.dumps(dict(cover="point_n21_L5/certificates/n21-original.txt", L=str(L), weight_denominator=W, sites=len(coords),
                                         records=recs, all_agree=all(r["agree"] for r in recs)), indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv[3:], sys.argv[2])
