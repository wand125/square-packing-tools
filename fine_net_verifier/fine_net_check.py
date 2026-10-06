#!/usr/bin/env python3
"""Second-system check of a fine-net density certificate: one command, one receipt.

    fine_net_check.py CANDIDATE.json --out DIR [--bin PATH] [--threads K] [--no-control]
    fine_net_check.py CANDIDATE.json --out DIR --repair [--bin WITNESS_BUILD] [--threshold P/Q]
                   [--max-witnesses K] [--witness-separation S]

Runs sqverify-fast (jlevy's clean-room verifier with the proof_net change) on every
direction of the candidate's declared net, with --confirm, and writes DIR/receipt.json.
On a refusal it also writes DIR/counterexamples.json (direction, t, centre, box, exact
coverage), for the repair step.

Control (unless --no-control): every mass scaled by f (total_mass rescaled) on 32 directions
spread over the net, for f = 0.985, 0.97, 0.95, 0.9 in turn until one is refused with an
exact counterexample. A scaling of 0.999 is not a reliable control: a candidate's least
capture is often 1.003 to 1.02, so 0.999 times it still covers.

Repair mode (--repair): a search aid, not a verification. It needs the build of branch
wand125/sqverify-witnesses, runs every direction at --threshold (default 10005/10000) and
collects up to --max-witnesses (default 32) refused boxes per direction whose centres are at
least --witness-separation (default 0.02) apart, each with its exact capture. They go to
DIR/counterexamples.json as {r, t, verdict, witnesses: [{x, y, dx, dy, exact_coverage,
exact_below_threshold}]}. Centres lie in the verifier's D4-reduced domain [L/2, U_r]^2; the
measure is D4-invariant, so any of the eight images is an equally valid row. No control.

Exit 0 only when the candidate is VERIFIED on every direction and the control is refused
(verdict PASS); with --no-control, verdict PASS_WITHOUT_CONTROL, which is not a receipt for
publication.
Needs Python 3.8 or later (standard library) and the built binary; the binary defaults to
sqverify_fast/target/release/sqverify-fast beside this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIGEST_KEYS = ["n", "L", "B", "rectangles", "points", "total_mass", "proof_net"]
FACTORS = [F(985, 1000), F(97, 100), F(95, 100), F(9, 10)]


def digest(d: dict) -> str:
    key = {k: d[k] for k in DIGEST_KEYS}
    return hashlib.sha256(json.dumps(key, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run(binary: str, cand: Path, d: dict, directions: str, threads: int, log: Path,
        extra: list[str] | None = None) -> tuple[int, list[dict], float]:
    side = F(d["L"])
    cmd = [binary, "--candidate", str(cand), "--n", str(d["n"]),
           "--side", f"{side.numerator}/{side.denominator}",
           "--directions", directions, "--threads", str(threads), "--confirm", *(extra or [])]
    start = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    seconds = time.monotonic() - start
    log.write_text(proc.stdout + ("\n# stderr\n" + proc.stderr if proc.stderr else ""))
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    if proc.returncode == 2 or not rows:
        rows.append({"kind": "admission", "status": "ADMISSION_REFUSED", "stderr": proc.stderr.strip()[-2000:]})
    return proc.returncode, rows, seconds


def summary_of(rows: list[dict]) -> dict:
    return next((r for r in rows if r.get("kind") in ("sqverify-fast-summary/v1", "admission")), {})


def counterexamples(rows: list[dict], step: F) -> list[dict]:
    out = []
    for r in sorted((r for r in rows if "r" in r), key=lambda r: r["r"]):
        if r["verdict"] == "verified":
            continue
        w = r.get("witness") or {}
        out.append({
            "r": r["r"], "t": str(r["r"] * step), "verdict": r["verdict"],
            "centre": [w.get("x"), w.get("y")], "box": [w.get("dx"), w.get("dy")],
            "certified_lower": w.get("centre_lower_bound"),
            "exact_below_threshold": w.get("exact_below_threshold"),
            "exact_coverage": w.get("exact_coverage"),
        })
    return out


def repair(a, cand: Path, d: dict, raw: bytes, step: F) -> int:
    extra = ["--threshold", a.threshold, "--max-witnesses", str(a.max_witnesses),
             "--witness-separation", str(a.witness_separation)]
    code, rows, seconds = run(a.bin, cand, d, "all", a.threads, a.out / "repair.jsonl", extra)
    found = []
    for r in sorted((r for r in rows if "r" in r), key=lambda r: r["r"]):
        if r["verdict"] == "verified":
            continue
        ws = r.get("witnesses") or ([r["witness"]] if r.get("witness") else [])
        found.append({"r": r["r"], "t": str(r["r"] * step), "verdict": r["verdict"],
                      "witnesses": [{k: w.get(k) for k in ("x", "y", "dx", "dy", "exact_coverage",
                                                             "exact_below_threshold")} for w in ws]})
    (a.out / "counterexamples.json").write_text(json.dumps(found, indent=1))
    result = {"schema": "fine-net-repair-search/v1", "candidate_digest": digest(d),
              "file_sha256": hashlib.sha256(raw).hexdigest(), "threshold": a.threshold,
              "max_witnesses": a.max_witnesses, "witness_separation": a.witness_separation,
              "directions": len([r for r in rows if "r" in r]), "directions_refused": len(found),
              "witnesses": sum(len(f["witnesses"]) for f in found), "seconds": round(seconds, 1),
              "source_sha256": (summary_of(rows).get("build") or {}).get("source_sha256")}
    (a.out / "repair.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--bin", default=str(HERE / "sqverify_fast/target/release/sqverify-fast"))
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--no-control", action="store_true")
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--threshold", default="10005/10000")
    ap.add_argument("--max-witnesses", type=int, default=32)
    ap.add_argument("--witness-separation", type=float, default=0.02)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    raw = a.candidate.read_bytes()
    d = json.loads(raw)
    cand = a.out / "candidate.json"
    cand.write_bytes(raw)  # the bytes checked are the bytes recorded
    step = F(d["proof_net"]["step"])
    count = d["proof_net"]["last"] + 1
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if a.repair:
        return repair(a, cand, d, raw, step)
    code, rows, seconds = run(a.bin, cand, d, "all", a.threads, a.out / "run.jsonl")
    summ = summary_of(rows)
    dirs = [r for r in rows if "r" in r]
    bad = counterexamples(rows, step)
    if bad:
        (a.out / "counterexamples.json").write_text(json.dumps(bad, indent=1))

    control = {"skipped": True, "refused": None}
    if not a.no_control:
        spread = ",".join(str(round(i * (count - 1) / 31)) for i in range(32))
        tries = []
        for f in FACTORS:
            c = json.loads(raw)
            for item in c["rectangles"] + c.get("points", []):
                item["mass"] = str(F(item["mass"]) * f)
            c["total_mass"] = str(sum(F(x["mass"]) for x in c["rectangles"] + c.get("points", [])))
            path = a.out / f"control-mass{f.numerator}_{f.denominator}.json"
            path.write_text(json.dumps(c))
            ccode, crows, csec = run(a.bin, path, c, spread, a.threads, a.out / f"control-{f.numerator}_{f.denominator}.jsonl")
            refused = [r for r in crows if "r" in r and r["verdict"] != "verified"]
            exact = sum(bool((r.get("witness") or {}).get("exact_below_threshold")) for r in refused)
            tries.append({"factor": str(f), "status": summary_of(crows).get("status"), "exit": ccode,
                          "directions": 32, "refused": len(refused), "exact_below_threshold": exact,
                          "seconds": round(csec, 1)})
            if exact > 0:
                break
        control = {"kind": "every mass times factor, 32 directions spread over the net",
                   "tries": tries, "refused": bool(tries and tries[-1]["exact_below_threshold"] > 0)}

    build = summ.get("build") or {}
    receipt = {
        "schema": "fine-net-check2-receipt/v1",
        "status": summ.get("status", "ERROR"),
        "exit": code,
        "n": d["n"], "L": d["L"], "B": d["B"], "proof_net": d["proof_net"], "total_mass": d["total_mass"],
        "directions_expected": count,
        "directions_checked": len(dirs),
        "directions_verified": sum(r["verdict"] == "verified" for r in dirs),
        "directions_failed": len(bad),
        "candidate_digest": digest(d),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "input_sha256": (summ.get("premises") or {}).get("input_sha256"),
        "verifier": {"name": "sqverify-fast", "source_sha256": build.get("source_sha256"),
                     "rustc": build.get("rustc"), "target": build.get("target"),
                     "binary_sha256": hashlib.sha256(Path(a.bin).read_bytes()).hexdigest()},
        "threads": a.threads, "started_utc": started,
        "seconds": round(seconds, 1),
        "control": control,
    }
    if summ.get("status") == "ADMISSION_REFUSED":
        receipt["admission_error"] = summ.get("stderr")
    checked = (receipt["status"] == "VERIFIED" and code == 0
               and receipt["directions_verified"] == count)
    if a.no_control:
        # A precheck may skip the control; a receipt for publication must not.
        receipt["verdict"] = "PASS_WITHOUT_CONTROL" if checked else "FAIL"
        ok = checked
    else:
        ok = checked and control["refused"]
        receipt["verdict"] = "PASS" if ok else "FAIL"
    (a.out / "receipt.json").write_text(json.dumps(receipt, indent=1))
    print(json.dumps({k: receipt[k] for k in ("verdict", "status", "directions_verified", "directions_expected",
                                                "directions_failed", "candidate_digest", "seconds")}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
