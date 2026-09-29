#!/usr/bin/env python3
"""Scale a running ladder's intermediate candidate and send it to the independent verifier,
without stopping the ladder.

While a ladder is stuck on one rung, the engine keeps minimising mass. Meanwhile a copy
of the same candidate is scaled up to just below the budget and verified. If it passes,
the rung can be skipped; if not, the ladder is untouched, so the attempt is cheap.

  python transfer/scale_and_verify.py <search dir> <out dir> [--target MASS] [--n N] [--solver-dir DIR]

The target mass defaults to n - 1/100 and must be below n (a certificate proves s(n) >= L only
when the total mass is below n). n is read from the candidate, or given with --n.

`<search dir>` is a directory containing candidate.json (e.g. a running search). It is
only read, never modified. certify.py is taken from the solver directory (default: see
ladder/paths.py) and is run unmodified.
"""
import argparse, json, shutil, subprocess, sys, time
from fractions import Fraction as F
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ladder'))
from paths import solver_dir  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('search', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--target', help='scaled total mass (default: n - 1/100); must be below n')
    ap.add_argument('--n', type=int, help='number of squares (default: the candidate\'s "n")')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--solver-dir', type=Path, help='directory with certify.py (default: see ladder/paths.py)')
    a = ap.parse_args()

    src = a.search / 'candidate.json'
    cand = json.loads(src.read_text())
    weights = [F(x) if isinstance(x, str) else F(str(x)) for x in cand['weights']]
    mass = sum(weights)
    n = a.n if a.n is not None else cand.get('n')
    if n is None:
        sys.exit('the candidate has no "n"; pass --n')
    n = int(n)
    if a.n is not None and cand.get('n') is not None and int(cand['n']) != n:
        sys.exit(f'--n {n} disagrees with the candidate\'s n = {cand["n"]}')
    target = F(a.target) if a.target is not None else n - F(1, 100)
    if not 0 < target < n:
        sys.exit(f'target mass {target} must be positive and below n = {n}; a mass >= n proves nothing')
    if mass >= target:
        sys.exit(f'mass {float(mass):.6f} is at or above the target {float(target)}; no scaling needed or possible')
    factor = target / mass
    print(f'L = {cand["L"]}  mass {float(mass):.9f} -> {float(target)}  factor {float(factor):.12f}')

    scaled = dict(cand)
    scaled['n'] = n
    scaled['weights'] = [str(w * factor) for w in weights]
    scaled['mass'] = float(target)
    # Always record provenance, so that "why this mass" can be traced later.
    scaled['scaling_experiment'] = {
        'source': str(src), 'source_mass_exact': str(mass),
        'factor_exact': str(factor), 'target_mass_exact': str(target),
        'scaled_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    check = sum(F(x) for x in scaled['weights'])
    assert check == target, f'scaled mass does not match: {check} != {target}'
    print(f'  exact check OK: scaled mass = {check} = {float(check)}')

    # Write the scaled candidate. certify.py requires an empty output directory,
    # so the candidate file is placed outside it.
    a.out.parent.mkdir(parents=True, exist_ok=True)
    cand_path = a.out.parent / (a.out.name + '.candidate.json')
    cand_path.write_text(json.dumps(scaled))
    print(f'  scaled candidate: {cand_path}')

    # certify.py generates the input, verifies and writes the certificate in one go; used unmodified.
    code = (a.solver_dir or solver_dir()).resolve()
    print(f'  running certify.py (workers={a.workers}) ...')
    t = time.time()
    r = subprocess.run([sys.executable, 'certify.py', str(cand_path.resolve()),
                        '--out', str(a.out.resolve()), '--workers', str(a.workers)],
                       cwd=code, capture_output=True, text=True, timeout=14400)
    elapsed = time.time() - t
    summary = a.out / 'verification_summary.json'
    if r.returncode != 0 or not summary.exists():
        print(f'  failed ({elapsed:.0f}s, exit code {r.returncode})')
        print((r.stdout or '')[-600:]); print((r.stderr or '')[-600:])
        sys.exit(1)
    sjson = json.loads(summary.read_text())
    print(f'\n  status = {sjson["status"]}  angles {sjson["angle_cases"]}  '
          f'nodes {sjson["nodes"]:,}  {elapsed:.0f}s')
    print('  minimum leaf lower bound:', sjson['minimum_printed_leaf_lower_bound'])
    if sjson['status'] != 'VERIFIED':
        print('  not verified: no certificate')
        sys.exit(1)
    print(f'  => certificate for s({n}) >= {cand["L"]} (total mass {target} < {n}): {a.out}')


if __name__ == '__main__':
    main()
