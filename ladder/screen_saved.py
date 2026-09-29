"""Screen an existing candidate at an exact budget, optionally prove if clean."""
import os
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
            'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('--code-dir', type=Path,
                    help='solver directory (default: see ladder/paths.py)')
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--reserve', type=Fraction, required=True)
    ap.add_argument('--boxes', type=int, default=200000)
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    if a.code_dir is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from paths import solver_dir
        a.code_dir = solver_dir(Path(__file__).resolve().parent)
    sys.path.insert(0, str(a.code_dir.resolve()))
    from global_separation_fast import separate_global
    from rectangle_rescue import scale, rescue
    d = json.loads(a.source.read_text())
    if 'n' in d and d['n'] != a.n:
        ap.error('source n mismatch')
    scaled = scale(d, a.n, a.reserve)
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out/'candidate.json').write_text(json.dumps(scaled))
    model = SimpleNamespace(L=float(Fraction(str(d['L']))),
                            B=float(Fraction(str(d['B']))), rhs=float(d['rhs']),
                            rectangles=np.asarray(d['rectangles']), atoms=[])
    weights = np.array([float(Fraction(w)) for w in scaled['weights']])
    bad, report = separate_global(model, SimpleNamespace(weights=weights),
                                   budget=a.boxes, max_rows=1000000)
    np.savez_compressed(a.out/'witnesses.npz', poses=bad)
    report.update(source=str(a.source.resolve()),
                  source_sha256=hashlib.sha256(a.source.read_bytes()).hexdigest(),
                  target_mass_exact=str(Fraction(a.n)-a.reserve))
    (a.out/'screen.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    if a.prove and report['status'] == 'SCREENED_ALL_NET_CENTERS':
        result = rescue(a.source, a.n, a.out/'proof', a.code_dir,
                        reserve=a.reserve, workers=1)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
