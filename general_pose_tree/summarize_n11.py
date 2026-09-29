"""Summarize run_n11.py JSONL outputs: agreement, timings, node-count distribution."""
import json
import sys
from pathlib import Path


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]


def main(out, paths):
    recs = []
    for p in paths:
        recs += [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]
    recs.sort(key=lambda r: r["row"])
    mins = [r for r in recs if r["mode"] == "minimize"]
    dis = [r for r in mins if not r["agree"]]
    below = [r for r in mins if r["recorded"] < 10**9]
    summ = dict(rows_checked=len(mins), agree=len(mins) - len(dis), disagree=[{k: r[k] for k in ("row", "minimum", "recorded")} for r in dis],
                witnesses_replayed=sum(1 for r in mins if r["witness_replayed"]),
                rows_below_1e9=[{k: r[k] for k in ("row", "minimum", "recorded", "agree")} for r in below],
                min_over_sample=min(r["minimum"] for r in mins),
                distinct_minima={str(v): sum(1 for r in mins if r["minimum"] == v) for v in sorted({r["minimum"] for r in mins})})
    for key in ("seconds", "boxes_expanded", "leaves", "cells", "max_depth", "max_heap"):
        xs = [r[key] for r in mins]
        summ[key] = dict(min=min(xs), p50=pct(xs, .5), p90=pct(xs, .9), p99=pct(xs, .99), max=max(xs), total=sum(xs))
    summ["slowest_rows"] = [{k: r[k] for k in ("row", "seconds", "boxes_expanded", "leaves")} for r in sorted(mins, key=lambda r: -r["seconds"])[:5]]
    mean = summ["seconds"]["total"] / len(mins)
    summ["estimate_all_12028_rows_seconds_single_process"] = mean * 12028
    Path(out).write_text(json.dumps(summ, indent=2) + "\n")
    print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
