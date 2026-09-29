"""Recheck Kleddamag's n=11 certificate rows with branch.py and compare to the recorded minima.

usage: run_n11.py CERT_DIR OUT.jsonl ROWSPEC [--certify] [--leaf N]
  ROWSPEC: comma-separated row numbers / ranges a-b, or @file (one row per line).
Writes one JSON line per row (appending, flushed), so partial runs are usable.
"""
import argparse
import json
import sys
import time
from fractions import Fraction as F
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure import load_kleddamag  # noqa: E402
from enclosure import centre_radius, core_margin  # noqa: E402
from branch import RowSolver  # noqa: E402


def parse_rows(spec):
    if spec.startswith("@"):
        return [int(x) for x in Path(spec[1:]).read_text().split()]
    rows = []
    for part in spec.split(","):
        if "-" in part:
            a, b = map(int, part.split("-"))
            rows += range(a, b + 1)
        else:
            rows.append(int(part))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cert_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("rows")
    ap.add_argument("--certify", action="store_true")
    ap.add_argument("--leaf", type=int, default=10)
    a = ap.parse_args()
    m, c = load_kleddamag(a.cert_dir / "global-certificate.json")
    assert m.budget() == c["budget_units"]
    recorded = json.loads((a.cert_dir / "evidence/portable/python.json").read_text())["rows"]
    done = set()
    if a.out.exists():
        done = {json.loads(l)["row"] for l in a.out.read_text().splitlines() if l.strip()}
    with a.out.open("a") as fh:
        for k in parse_rows(a.rows):
            if k in done:
                continue
            ra, rb, t, B = c["entries"][k]
            assert core_margin(c["A"], B, ra, rb, t) > 0
            r = centre_radius(c["A"], ra, rb)
            t0 = time.monotonic()
            s = RowSolver(m, c["L"], B, t, r)
            setup = time.monotonic() - t0
            exp = recorded[k]["minimum_units"]
            assert recorded[k]["row"] == k
            if a.certify:
                res = s.certify(c["minimum_units"], leaf_size=a.leaf)
                rec = dict(row=k, mode="certify", ok=res["ok"], recorded=exp)
            else:
                res = s.minimize(leaf_size=a.leaf)
                rec = dict(row=k, mode="minimize", minimum=res["minimum"], recorded=exp,
                           agree=res["minimum"] == exp, witness=res["witness"],
                           witness_replayed=res.get("witness_replayed", False))
            rec.update(setup_seconds=setup, **{x: res[x] for x in (
                "seconds", "boxes_expanded", "leaves", "max_depth", "cells", "nodes_created",
                "outside_pruned", "bound_pruned")})
            if "max_heap" in res:
                rec["max_heap"] = res["max_heap"]
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(k, rec.get("minimum", rec.get("ok")), exp, round(rec["seconds"], 2), rec["boxes_expanded"], flush=True)


if __name__ == "__main__":
    main()
