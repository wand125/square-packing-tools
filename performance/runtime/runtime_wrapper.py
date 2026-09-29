"""Common launch adapter; preserve original rung, pricing, model, and proof logic.

    python performance/runtime/runtime_wrapper.py ladder/rung.py <case key> <config.json>

Runs the given entry script with Master.solve replaced by the managed working-row LP
(runtime_solver.py). The solver directory is found as in ladder/paths.py.
Phase metrics go to $SP_PERFORMANCE_DIR (default ./performance_metrics).
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[key]='1'
import runpy, sys, json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ladder'))
from paths import solver_dir, results_root

def configure_screen(entry, args):
    """Retain full audits, but admit saved witnesses to the LP in small batches."""
    config = Path(args[-1]) if args and args[-1].endswith('.json') else entry.parent/(args[0]+'.json') if args else None
    cfg = json.loads(config.read_text()) if config and config.is_file() else {}
    if cfg.get('screen_audit_batch', 16) == 16:
        os.environ.setdefault('SP_SCREEN_AUDIT_BATCH', '16')
        key = args[0] if args else entry.stem
        os.environ.setdefault('SP_SCREEN_WITNESS_DIR', str(results_root(entry.parent)/key/'witness-archive'))

def install(Master, managed):
    original = Master.solve
    def solve(self, *args, **kwargs):
        if len(self.atoms) or args or kwargs or getattr(self,'_runtime_disabled',False):
            return original(self, *args, **kwargs)
        cached = getattr(self, '_runtime_dual', None)
        dual = np.zeros(len(self.poses))
        if cached is not None:
            poses, values = cached
            if len(poses)<=len(self.poses) and np.array_equal(poses,self.poses[:len(poses)]):
                dual[:len(poses)] = values
        try:
            solution, _ = managed(self, dual)
        except RuntimeError:
            # Keep the caller's original simplex/IPM residual-recovery contract.
            # Disable this adapter for this model after a failed managed solve.
            self._runtime_disabled = True
            return original(self, *args, **kwargs)
        self._runtime_dual = (self.poses.copy(), solution.dual.copy())
        return solution
    Master.solve = solve

def main():
    entry = Path(sys.argv[1]).resolve(); args = sys.argv[2:]
    release = Path(__file__).resolve().parent
    os.environ.setdefault('SP_PERFORMANCE_DIR',str(Path.cwd()/'performance_metrics'))
    os.environ['SP_PERFORMANCE_RELEASE'] = release.name
    configure_screen(entry, args)
    sys.path.insert(0,str(solver_dir(entry.parent))); sys.path.insert(0,str(release))
    from master import Master
    from runtime_solver import solve
    install(Master, solve)
    sys.path.insert(0,str(entry.parent))
    sys.argv = [str(entry)]+args
    runpy.run_path(str(entry),run_name='__main__')
if __name__=='__main__': main()
