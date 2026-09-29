"""Quick checks that the tools run from a fresh clone.

The end-to-end ladder test (LP -> proof -> transfer rung -> budget-recovery rung) compiles the
verifier and takes about a minute; it runs only with SP_SLOW_TESTS=1.
"""
import importlib
import json
import math
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
MODULES = [
    # solver/
    'master', 'geometry', 'fast_geometry', 'pricing', 'refinement', 'certify', 'advance',
    'plot_solution', 'points', 'residual_dump', 'rectangle_rescue', 'global_separation_fast',
    'axis_screen_fast', 'net_screen_scratch', 'overlap_scratch',
    # ladder/
    'paths', 'edge_pricing', 'residual_recovery', 'checkpoint_basis',
    # performance/
    'runtime_metrics', 'runtime_solver', 'runtime_wrapper', 'working_rows',
    'batch16', 'witness_batches', 'parallel_screen', 'axis_cached',
]


def run(script, *args, cwd, env=None):
    p = subprocess.run([sys.executable, str(REPO / script), *map(str, args)], cwd=cwd,
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return p.stdout


@pytest.mark.parametrize('name', MODULES)
def test_import(name):
    importlib.import_module(name)


def test_every_file_compiles(tmp_path):
    files = [p for p in REPO.rglob('*.py') if '.git' not in p.parts]
    assert files
    for i, p in enumerate(files):
        py_compile.compile(str(p), cfile=str(tmp_path / f'{i}.pyc'), doraise=True)


def sobol_poses(power=8):
    from scipy.stats import qmc
    poses = qmc.Sobol(3, scramble=True, seed=1).random_base2(power)
    poses[:, :2] = 2 * poses[:, :2] - 1
    return poses


def grid_master(L, k=4):
    from master import Master
    e = .001; xs = np.linspace(e, L - e, k + 1)
    rects = [[xs[i], xs[j], xs[i + 1], xs[j + 1]] for i in range(k) for j in range(k)] + [[e, e, L - e, L - e]]
    return Master(L, .9977, np.array(rects), rhs=1.001)


def test_master_solves_one_lp():
    m = grid_master(1.5)
    m.add_rows(sobol_poses())
    sol = m.solve()
    assert np.isfinite(sol.mass) and sol.mass > 0
    assert float((m.A @ sol.weights).min()) >= m.rhs - 2e-7


def test_l_cap_cli(tmp_path):
    out = [json.loads(x) for x in run('transfer/l_cap.py', 29, 61, cwd=tmp_path).splitlines()]
    alpha = 399908091 / 400000000
    assert out[0]['alpha'] == '399908091/400000000'
    assert out[0]['n'] == 29 and out[0]['L_cap'] == math.floor(alpha * out[0]['UB'] * 1000 - 1e-6) / 1000
    assert out[1]['L_cap'] < out[1]['UB']


@pytest.mark.parametrize('target', ['28.9', '1', '1.5'])
def test_scale_and_verify_refuses_mass_at_or_above_n(tmp_path, target):
    # n = 1 with the old default target (28.9) used to print a certificate claim.
    (tmp_path / 's').mkdir()
    (tmp_path / 's/candidate.json').write_text(json.dumps(dict(n=1, L='1.5', weights=['0.5'], rectangles=[[0, 0, 1, 1]])))
    r = subprocess.run([sys.executable, str(REPO / 'transfer/scale_and_verify.py'), 's', 'out', '--target', target],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode != 0 and 'below n' in r.stderr and 'certificate for' not in r.stdout
    assert not (tmp_path / 'out').exists()


def test_next_step_cli(tmp_path):
    (tmp_path / 'candidate.json').write_text(json.dumps(dict(n=5, L='2.7', mass=4.5)))
    d = json.loads(run('transfer/next_step.py', tmp_path, cwd=tmp_path))
    assert d['budget'] == 4.99 and d['L_max_L2'] == round(2.7 * math.sqrt(4.99 / 4.5), 4)
    assert float(d['suggested_next']) >= 2.7 + .0025


def test_make_edge_scales_rectangles(tmp_path):
    rects = np.array([[.1, .1, .9, .9], [.5, .2, 1.4, 1.3]]); poses = sobol_poses(4)
    np.savez_compressed(tmp_path / 'state.npz', rectangles=rects, poses=poses)
    out = run('transfer/make_edge.py', 'state.npz', '--n', 3, '--L', 1.6, '--source-L', 1.5,
              '--key', 'e1', cwd=tmp_path)
    assert out.splitlines()[-1].split()[-2:] == ['e1', str(Path('rungs/e1.json'))]
    cfg = json.loads((tmp_path / 'rungs/e1.json').read_text())
    assert cfg['target'] == 3 - 0.01 and cfg['pricing_rounds'] == 3 and cfg['checkpoint'] == 'e1-rows.npz'
    z = np.load(tmp_path / 'rungs/e1-rows.npz')
    np.testing.assert_array_equal(z['rectangles'], rects * (1.6 / 1.5))
    np.testing.assert_array_equal(z['poses'], poses)


@pytest.mark.skipif(os.environ.get('SP_SLOW_TESTS') != '1', reason='set SP_SLOW_TESTS=1 (about a minute)')
@pytest.mark.skipif(shutil.which('g++') is None, reason='the verifier needs g++')
def test_end_to_end_ladder(tmp_path):
    from global_separation_fast import separate_global
    # A certified n=3 parent at L=1.5.
    m = grid_master(1.5); m.add_rows(sobol_poses(10)); sol = m.solve()
    bad, report = separate_global(m, SimpleNamespace(weights=sol.weights * (2.99 / sol.mass)), budget=50000, max_rows=1000)
    assert report['status'] == 'SCREENED_ALL_NET_CENTERS' and sol.mass < 2.99
    (tmp_path / 'cand.json').write_text(json.dumps(dict(n=3, L=1.5, B=.9977, rhs=1.001, rectangles=m.rectangles.tolist(),
                                                        weights=sol.weights.tolist(), mass=sol.mass, globally_verified=False)))
    run('solver/rectangle_rescue.py', 'cand.json', '--n', 3, '--out', 'proof3', '--code-dir', REPO / 'solver',
        '--reserve', '0.01', '--workers', 2, cwd=tmp_path)
    # Neighbour transfer n=3 -> n=4 at L=1.6.
    run('transfer/make_transfer.py', 'proof3', '--parent-n', 3, '--target-n', 4, '--L', '1.6', '--key', 't', cwd=tmp_path)
    run('ladder/rung.py', 't', 'rungs/t.json', cwd=tmp_path)
    progress = json.loads((tmp_path / 'results/t/progress.json').read_text())
    assert progress['records'][-1]['status'] == 'CERTIFIED'
    # Budget recovery from the saved rows/columns, scaled to L=1.55.
    np.savez_compressed(tmp_path / 'state.npz', rectangles=m.rectangles, poses=m.poses)
    run('transfer/make_edge.py', 'state.npz', '--n', 3, '--L', 1.55, '--source-L', 1.5, '--key', 'e',
        '--pricing-rounds', 1, cwd=tmp_path)
    run('ladder/edge_rung.py', 'e', 'rungs/e.json', cwd=tmp_path)
    progress = json.loads((tmp_path / 'results/e/progress.json').read_text())
    assert progress['records'][-1]['status'] == 'CERTIFIED'
