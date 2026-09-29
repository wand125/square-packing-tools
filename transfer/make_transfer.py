#!/usr/bin/env python3
"""Write a neighbour-n rung config from a CERTIFIED parent (forward: larger n, larger L).

    python transfer/make_transfer.py <parent proof dir> --parent-n PN --target-n TN --L L
                                     [--key KEY] [--out-dir DIR]

<parent proof dir> is a rectangle_rescue proof directory (result.json, candidate.json,
certificate/). The parent proof is validated for parent_n, then a fixed-support config with
parent_n and budget target_n - 1/100 is written to <out-dir>/<key>.json, and the command that
runs it with ladder/rung.py is printed. The target proof is independent: parent weights are
re-optimized, never inherited as a proof.
"""
import argparse
import json
import os
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ladder'))
from paths import solver_dir, REPO  # noqa: E402


def est_mem_gb(rows, cols, factor=2.5, pricing=False):
    """Advisory peak memory of a rung (GB), calibrated on 54 running jobs: resident memory is
    1.9-2.5x the dense rows x cols float64 matrix (simplex; IPM up to 5x), rows grow ~30% while it runs,
    and a budget-recovery pricing pass takes ~0.1 MB per row."""
    g = factor * rows * cols * 8e-9 * 1.3
    if pricing: g = max(g, 1.0e-4 * rows)
    return round(g + 0.5, 1)


def parent_rows(proof):
    """Rows the parent rung ended with (its progress.json): a next rung or transfer usually grows to about that."""
    try:
        recs = json.loads((proof.parent / 'progress.json').read_text())['records']
        return max((r.get('rows') or 0) for r in recs) or 30000
    except Exception: return 30000


def _shown(path):
    """Path as typed in the printed command: relative to the current directory when below it."""
    rel = os.path.relpath(path)
    return str(path) if rel.startswith('..') else rel


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('proof', type=Path, help='certified parent proof directory')
    ap.add_argument('--parent-n', type=int, required=True)
    ap.add_argument('--target-n', type=int, required=True)
    ap.add_argument('--L', required=True, help='target L, e.g. 6.755 (kept as text)')
    ap.add_argument('--key', help='case key (default n<TN>_from_n<PN>_L<digits>)')
    ap.add_argument('--out-dir', type=Path, default=Path('rungs'), help='where the config is written (default ./rungs)')
    ap.add_argument('--proof-workers', type=int, help='verifier workers for the final proof')
    ap.add_argument('--max-screen-rows', type=int,
                    help='cap rows added per screen (large supports can run out of memory)')
    ap.add_argument('--all-ipm', action='store_true', help='use IPM for every LP (no simplex, no residual recovery)')
    a = ap.parse_args()
    proof = a.proof.resolve(); pn = a.parent_n; tn = a.target_n; L = a.L
    key = a.key or f"n{tn}_from_n{pn}_L{L.replace('.', '')}"

    sys.path.insert(0, str(solver_dir()))
    from rectangle_rescue import validate_result
    if json.loads((proof / 'result.json').read_text())['status'] != 'CERTIFIED': raise SystemExit('parent not certified')
    meta = validate_result(proof / 'candidate.json', proof / 'certificate', pn)
    if Fraction(L) < Fraction(meta['L']):
        # A smaller L needs support contraction; advance.transfer (used by ladder/rung.py) requires L to increase.
        raise SystemExit(f'L {L} is below the parent L {meta["L"]}: support contraction is not implemented by ladder/rung.py')
    cfg = dict(n=tn, parent_n=pn, L=L, parent=str(proof / 'certificate/certified_candidate.json'), mode='own_fixed',
               targets=[f'{tn - 1}.99'], keep_inactive=True, screen_boxes=200000, initial_solver='simplex',
               continue_ipm=False, residual_ipm_recovery=True,
               rationale=f'Neighbour transfer from independently certified n{pn} rectangle L{meta["L"]} to n{tn} at L{L}; '
                         f'fixed parent support re-optimized for budget {tn - 1}.99; independent 201-direction proof; original gates.')
    if a.proof_workers: cfg['proof_workers'] = a.proof_workers
    if a.max_screen_rows: cfg['max_screen_rows'] = a.max_screen_rows
    if a.all_ipm: cfg.update(initial_solver='ipm', continue_ipm=True, residual_ipm_recovery=False)

    out = a.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    f = out / f'{key}.json'
    if f.exists(): raise SystemExit(f'config exists: {f}')
    f.write_text(json.dumps(cfg, indent=2))
    ncols = len(json.loads((proof / 'certificate/certified_candidate.json').read_text()).get('rectangles', [])) or 2500
    mem = est_mem_gb(parent_rows(proof), ncols, 5.0 if cfg.get('continue_ipm') else 2.5)
    command = f'python {_shown(REPO / "ladder/rung.py")} {key} {_shown(f)}'
    print(json.dumps(dict(parent=meta, key=key, config=str(f), est_mem_gb=mem, command=command)))
    print(command)


if __name__ == '__main__':
    main()
