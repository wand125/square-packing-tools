"""Compare supports/pricing on a saved complete row set; no job submission.

Outputs are unverified candidates and resumable states, NOT certificates.
"""
import os
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
            'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
import argparse
import hashlib
import itertools
import json
from fractions import Fraction
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--code-dir', type=Path,
                    help='solver directory (default: see ladder/paths.py)')
    ap.add_argument('--checkpoint', type=Path, required=True)
    ap.add_argument('--extra-support', type=Path)
    ap.add_argument('--L', type=float, required=True)
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--target', type=float, required=True)
    ap.add_argument('--pricing-rounds', type=int, default=1)
    ap.add_argument('--pricing', choices=['edges', 'legacy'], default='edges')
    ap.add_argument('--min-side', type=float, default=.001,
                    help='Minimum side for NEW edge-pricing columns only')
    ap.add_argument('--reuse-solution', action='store_true',
                    help='Recheck a saved primal/dual pair on rebuilt full A, avoiding a cold LP')
    ap.add_argument('--screen', action='store_true')
    ap.add_argument('--repair-rounds', type=int, default=0)
    ap.add_argument('--monitor-format', action='store_true',
                    help='Use the existing rung progress schema for watch discovery')
    ap.add_argument('--case-key')
    ap.add_argument('--legacy-fallback', action='store_true')
    ap.add_argument('--reprice-on-budget', action='store_true',
                    help='Try one edge-pricing LP when a repair exceeds target')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    if a.code_dir is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from paths import solver_dir
        a.code_dir = solver_dir(Path(__file__).resolve().parent)
    if not 0 < a.target < a.n or a.pricing_rounds < 0 or a.repair_rounds < -1:
        ap.error('require 0 < target < n; repair-rounds=-1 means unlimited')
    if (a.prove or a.repair_rounds or a.reprice_on_budget) and not a.screen:
        ap.error('--prove/--repair-rounds/--reprice-on-budget require --screen')
    sys.path.insert(0, str(a.code_dir.resolve()))
    from master import Master
    from edge_pricing import propose_edges
    from pricing import propose
    a.out.mkdir(parents=True, exist_ok=False)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    manifest = {k: str(v) if isinstance(v, Path) else v for k, v in vars(a).items()}
    manifest['input_sha256'] = sha(a.checkpoint)
    manifest['engine_sha256'] = {p.name: sha(p) for p in sorted(a.code_dir.glob('*.py'))}
    manifest['research_sha256'] = {p.name: sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
    if a.extra_support:
        manifest['extra_sha256'] = sha(a.extra_support)
    (a.out/'experiment.json').write_text(json.dumps(manifest, indent=2))
    records = []; started = perf_counter()
    def emit(record):
        record['elapsed'] = perf_counter()-started
        records.append(record)
        payload = dict(case=a.case_key or a.out.name, seconds=record['elapsed'], records=records) if a.monitor_format else records
        temporary = a.out/'progress.tmp'
        temporary.write_text(json.dumps(payload, indent=2)); temporary.replace(a.out/'progress.json')
        try:
            print(json.dumps(record), flush=True)
        except BrokenPipeError:
            pass  # Durable progress files remain authoritative after UI restarts.
    data = np.load(a.checkpoint, allow_pickle=False)
    for key, value in [('L', a.L), ('B', .9977), ('rhs', 1.001)]:
        if key in data and float(data[key]) != value:
            raise ValueError(f'checkpoint {key} mismatch')
    m = Master(a.L, .9977, data['rectangles'], rhs=1.001)
    # Keep the complete source row set. Geometry is recomputed for new columns.
    for start in range(0, len(data['poses']), 2048):
        m.add_rows(data['poses'][start:start+2048])
    m._check(m.h.setOptionValue('solver', 'ipm'))
    m._check(m.h.setOptionValue('output_flag', True))
    m._check(m.h.setOptionValue('log_to_console', False))
    m._check(m.h.setOptionValue('log_file', str((a.out/'highs.log').resolve())))
    emit(dict(operation='loaded', rows=len(m.poses), columns=len(m.rectangles)))
    lp_iteration = 0
    def solve(label, saved=None):
        nonlocal lp_iteration
        s = m.solve() if saved is None else saved  # Original gates remain authoritative.
        np.savez_compressed(a.out/f'{label}-state.npz', rectangles=m.rectangles,
                            poses=m.poses, weights=s.weights, dual=s.dual,
                            L=m.L, B=m.B, rhs=m.rhs)
        np.savez_compressed(a.out/'resume-state.tmp.npz', rectangles=m.rectangles,
                            poses=m.poses, L=m.L, B=m.B, rhs=m.rhs)
        (a.out/'resume-state.tmp.npz').replace(a.out/'resume-state.npz')
        (a.out/'resume.json').write_text(json.dumps(dict(next_iteration=lp_iteration+1,
                                                       mode='edge_budget_recovery')))
        (a.out/f'{label}-candidate.json').write_text(json.dumps(dict(
            n=a.n, L=a.L, B=m.B, rhs=m.rhs, mass=s.mass,
            rectangles=m.rectangles.tolist(), weights=s.weights.tolist(),
            globally_verified=False)))
        emit(dict(operation='lp', iteration=lp_iteration, label=label, mass=s.mass,
                  target=a.target, under_target=s.mass<a.target,
                  minimum=s.min_coverage, dual_violation=s.dual_violation,
                  duality_gap=s.duality_gap, seconds=s.seconds,
                  columns=len(m.rectangles), rows=len(m.poses)))
        lp_iteration += 1
        return s
    try:
        saved = None
        if a.reuse_solution:
            # Old resume files contain no solution; fail instead of guessing.
            weights, dual = data['weights'], data['dual']
            if not all(key in data for key in ['L', 'B', 'rhs']):
                companion = a.checkpoint.with_name(a.checkpoint.name.replace('-state.npz', '-candidate.json'))
                d = json.loads(companion.read_text())
                if any(d[k] != v for k, v in [('L', a.L), ('B', m.B), ('rhs', m.rhs)]):
                    raise ValueError('saved candidate geometry mismatch')
                if not np.array_equal(d['rectangles'], m.rectangles) or not np.array_equal(d['weights'], weights):
                    raise ValueError('saved candidate/state mismatch')
            if (weights.shape != (m.A.shape[1],) or dual.shape != (len(m.poses),)
                    or not np.isfinite(weights).all() or not np.isfinite(dual).all()
                    or np.any(weights < 0) or np.any(dual < 0)):
                raise ValueError('invalid saved primal/dual')
            minimum = float(np.min(m.A@weights))
            violation = max(0., float(np.max(m.A.T@dual))-1)
            mass = float(weights.sum()); gap = float(mass-m.rhs*dual.sum())
            if minimum < m.rhs-2e-7 or violation > 2e-5 or abs(gap) > 1e-4:
                raise ValueError('saved primal/dual failed original residual gates')
            saved = SimpleNamespace(weights=weights, dual=dual, mass=mass,
                min_coverage=minimum, dual_violation=violation, duality_gap=gap, seconds=0.)
            emit(dict(operation='saved_solution_revalidated', minimum=minimum,
                      dual_violation=violation, duality_gap=gap))
        label = 'baseline'; s = solve(label, saved)
        if a.extra_support:
            extra = np.load(a.extra_support, allow_pickle=False)
            for key, value in [('L', a.L), ('B', m.B), ('rhs', m.rhs)]:
                if key in extra and float(extra[key]) != value:
                    raise ValueError(f'extra support {key} mismatch')
            added = m.add_columns(extra['rectangles'])
            emit(dict(operation='union', added=added))
            before = s.mass; label = 'union'; s = solve(label)
            if s.mass > before+1e-4:
                raise RuntimeError('union increased mass beyond numerical gates')
        for iteration in range(a.pricing_rounds):
            if a.pricing == 'edges':
                columns, report = propose_edges(m, s, min_side=a.min_side)
            else:
                columns, report = propose(m, s, seed=926180+iteration,
                    samples_power=8, local_starts=1, max_columns=32,
                    widths=(1/64, 1/16, 1/4, 1/2))
            (a.out/f'pricing-{iteration}.json').write_text(json.dumps(
                dict(columns=columns, report=report), indent=2))
            emit(dict(operation='pricing', iteration=iteration, **report))
            if not columns:
                break
            m.add_columns([c['rectangle'] for c in columns])
            before = s.mass; label = f'priced-{iteration}'; s = solve(label)
            if s.mass > before+1e-4:
                raise RuntimeError('pricing increased mass beyond numerical gates')
        termination = 'FINITE_LP_COMPARISON_ONLY'
        if a.screen:
            from global_separation_fast import separate_global
            from rectangle_rescue import rescue
            stalled_pricing = 0
            rounds = itertools.count() if a.repair_rounds == -1 else range(a.repair_rounds+1)
            for iteration in rounds:
                if s.mass >= a.target and a.reprice_on_budget:
                    columns, report = propose_edges(m, s, min_side=a.min_side)
                    if a.legacy_fallback and (not columns or stalled_pricing):
                        legacy, legacy_report = propose(m, s, seed=926180+iteration,
                            samples_power=8, local_starts=1, max_columns=32,
                            widths=(1/64, 1/16, 1/4, 1/2))
                        columns.extend(legacy)
                        report['legacy_fallback'] = legacy_report
                    (a.out/f'budget-pricing-{iteration}.json').write_text(json.dumps(
                        dict(columns=columns, report=report), indent=2))
                    emit(dict(operation='budget_pricing', iteration=iteration, **report))
                    if columns:
                        m.add_columns([c['rectangle'] for c in columns])
                        before = s.mass; label = f'budget-priced-{iteration}'; s = solve(label)
                        if s.mass > before+1e-4:
                            raise RuntimeError('budget pricing increased mass beyond numerical gates')
                        stalled_pricing = stalled_pricing+1 if before-s.mass < 1e-7 else 0
                        if s.mass >= a.target and stalled_pricing < 3 and (a.repair_rounds == -1 or iteration < a.repair_rounds):
                            emit(dict(operation='budget_recovery_continue', iteration=iteration,
                                      mass_reduction=before-s.mass, stagnant_rounds=stalled_pricing))
                            continue
                if s.mass >= a.target:
                    emit(dict(operation='screen', status='OVER_TARGET', mass=s.mass))
                    termination = 'BUDGET_EXHAUSTED'
                    break
                bad, report = separate_global(m,
                    SimpleNamespace(weights=s.weights*(a.target/s.mass)),
                    budget=200000, max_rows=1000000)
                np.savez_compressed(a.out/f'screen-{iteration}-witnesses.npz', poses=bad)
                emit(dict(report, operation='screen', iteration=lp_iteration-1,
                          screen_round=iteration, returned=len(bad), unknown=len(report['unknown_angles'])))
                if report['status'] == 'SCREENED_ALL_NET_CENTERS':
                    termination = 'SCREENED_NOT_CERTIFIED'
                    if a.prove:
                        result = rescue(a.out/f'{label}-candidate.json', a.n,
                            a.out/f'proof-{iteration}', a.code_dir,
                            reserve=Fraction(a.n)-Fraction(str(a.target)), workers=1)
                        emit(dict(operation='proof', result=result))
                        termination = result['status']
                    break
                added = m.add_rows(bad) if len(bad) else 0
                # Includes the last screen's constraints even at the review limit.
                np.savez_compressed(a.out/'resume-state.tmp.npz', rectangles=m.rectangles,
                                    poses=m.poses, L=m.L, B=m.B, rhs=m.rhs)
                (a.out/'resume-state.tmp.npz').replace(a.out/'resume-state.npz')
                emit(dict(operation='repair_rows', added=added, rows=len(m.poses)))
                if not added or iteration == a.repair_rounds:
                    termination = ('REVIEW_LIMIT_WITH_WITNESSES' if added else
                        'SCREEN_INCOMPLETE' if report['unknown_angles'] else 'STALLED_NO_CHANGE')
                    break
                label = f'repair-{iteration}'; s = solve(label)
        verified = bool(a.screen and a.prove and any(r.get('operation') == 'proof' and
                        r['result']['status'] == 'CERTIFIED' for r in records))
        emit(dict(status=(('CERTIFIED' if verified else
                          'BUDGET_EXHAUSTED' if termination=='BUDGET_EXHAUSTED' else
                          'ITERATIONS_EXHAUSTED' if termination=='REVIEW_LIMIT_WITH_WITNESSES' else
                          'STALLED_NO_CHANGE') if a.monitor_format else 'COMPARISON_COMPLETE'),
                  reason=termination,
                  globally_verified=verified))
    except Exception as e:
        emit(dict(status='ERROR', error=repr(e)))
        raise


if __name__ == '__main__':
    main()
