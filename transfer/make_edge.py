#!/usr/bin/env python3
"""Write a budget-recovery (4-edge pricing) rung from a job's saved rows and columns.

    python transfer/make_edge.py <source> --n N --L L --key NEWKEY
                                 [--pricing-rounds 3] [--source-L SRC_L] [--out-dir DIR]

<source> is either a saved state (resume-state.npz) or a job's results directory
<runs>/results/<key>/. For a directory the checkpoint is <dir>/resume-state.npz, or, when the
job certified or stopped without solving a new LP, the input it resumed from
(<runs>/<key>-resume.npz). Only rectangles and poses are kept (the runner rejects a state that
records a different L).

With --source-L, the rectangles are scaled by L/source_L first (budget recovery plus shrinking:
start low, recover budget, then climb gradually).

Writes <out-dir>/<NEWKEY>-rows.npz and <out-dir>/<NEWKEY>.json and prints the command that runs
it with ladder/edge_rung.py: price first, then screen, repair (pricing again when over budget)
and prove with the original gates.
"""
import argparse
import json
import os
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ladder'))
from paths import REPO  # noqa: E402


def est_gb(rows, cols):
    """Advisory peak memory of a budget-recovery rung (GB). Measured: the LP/screen phase takes 2-5x the dense
    rows x cols matrix (n29 109686 x 3060: 11.4 GB), the pricing phase about 0.1 MB per row (n26 77627 rows: 6.3 GB,
    n31 115096 rows: 15 GB). Rows grow while it runs, so take the larger of the two with room."""
    return max(3.0 * rows * cols * 8e-9 * 1.3, 1.0e-4 * rows) + 0.5   # recalibrated on 8 running rungs (median 2.45x dense)


def checkpoint_of(source):
    if source.is_dir():
        src = source / 'resume-state.npz'
        if not src.exists(): src = source.parent.parent / f'{source.name}-resume.npz'
        return src, source.name
    return source, source.stem


def _shown(path):
    """Path as typed in the printed command: relative to the current directory when below it."""
    rel = os.path.relpath(path)
    return str(path) if rel.startswith('..') else rel


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('source', type=Path, help='resume-state.npz, or a job results directory')
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--L', type=float, required=True)
    ap.add_argument('--key', required=True, help='case key of the new rung')
    ap.add_argument('--pricing-rounds', type=int, default=3)
    ap.add_argument('--source-L', type=float, help='L the saved state was solved at; rectangles are scaled by L/source_L')
    ap.add_argument('--out-dir', type=Path, default=Path('rungs'), help='where config and checkpoint are written (default ./rungs)')
    a = ap.parse_args()
    n, L, newkey, rounds, srcL = a.n, a.L, a.key, a.pricing_rounds, a.source_L
    src, key = checkpoint_of(a.source.resolve())
    if not src.exists(): raise SystemExit(f'no saved state for {a.source}')
    z = np.load(src)
    out = a.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    ck = f'{newkey}-rows.npz'
    f = out / f'{newkey}.json'
    if f.exists(): raise SystemExit(f'config exists: {f}')
    if (out / ck).exists(): raise SystemExit(f'checkpoint exists: {out / ck}')
    need = est_gb(len(z['poses']), len(z['rectangles']))
    rects, poses = z['rectangles'].astype(float), z['poses'].astype(float)
    if srcL:
        rects = rects * (L / srcL)   # poses are normalised (x, y in [-1, 1] of the free range, angle / (pi/4)): they do not depend on L
    np.savez_compressed(out / ck, rectangles=rects, poses=poses)
    cfg = dict(n=n, L=L, target=n - 0.01, checkpoint=ck, source=str(src), source_L=srcL, scale=(L / srcL if srcL else 1.0), pricing_rounds=rounds, min_side=0.001,
               solver='ipm', threads=1, repair_rounds=-1, reprice_on_budget=True, legacy_fallback=True, target_is_not_certificate=True,
               rationale=f'Budget recovery rung: from the saved rows/columns of {key} ({len(z["rectangles"])} columns, '
                         f'{len(z["poses"])} rows)' + (f' scaled from L{srcL}' if srcL else '') + f' at L{L}, {rounds} rounds of 4-edge pricing first, then screen, repair and prove with the original gates.')
    f.write_text(json.dumps(cfg, indent=1))
    command = f'python {_shown(REPO / "ladder/edge_rung.py")} {newkey} {_shown(f)}'
    print(json.dumps(dict(key=newkey, n=n, L=L, source=str(src), source_L=srcL, scale=(L / srcL if srcL else 1.0),
                          columns=len(z['rectangles']), rows=len(z['poses']), est_mem_gb=round(need, 1), config=str(f), command=command)))
    print(command)


if __name__ == '__main__':
    main()
