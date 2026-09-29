"""Managed working LP: full gates, bounded reuse, one cold recovery, measured backoff."""
from working_rows import solve_working_rows as core
from runtime_metrics import phase
from time import perf_counter
import numpy as np

def solve(master, dual, **options):
    started = perf_counter()
    state = getattr(master, '_runtime_solver_state', None)
    if state is None:
        state = dict(cold_rate=None, slow=0, cooldown=0)
        master._runtime_solver_state = state
    requested = options.pop('reuse', True)
    reuse = requested and state['cooldown'] == 0
    if state['cooldown']: state['cooldown'] -= 1
    if not reuse and hasattr(master, '_working_rows_cache'):
        del master._working_rows_cache
    had_cache = reuse and hasattr(master, '_working_rows_cache')
    with phase('lp') as evidence:
        fallback = None
        recovery_strategy = None
        try:
            solution, report = core(master, dual, reuse=reuse, **options)
        except RuntimeError as exc:
            # A cold solve without any saved row hints may fail on its prefix
            # subset. Retry a different seed once; the full model is unchanged.
            unseeded = len(dual)>16 and not np.any(dual)
            if not had_cache and not unseeded: raise
            # Retry exactly once with the same complete finite model. The cold
            # result must pass every original gate; a second failure propagates.
            if hasattr(master, '_working_rows_cache'): del master._working_rows_cache
            fallback = str(exc)
            recovery_dual = dual
            recovery_strategy = 'cold_same_seed'
            if not had_cache:
                recovery_dual = np.zeros_like(dual, dtype=float)
                recovery_dual[-16:] = 1.
                recovery_strategy = 'cold_newest_rows'
            solution, report = core(master, recovery_dual, reuse=False, **options)
            state.update(cooldown=3, slow=0)
        rate = solution.seconds/max(master.A.nnz,1)
        if not report['reused_solver']:
            state['cold_rate'] = rate
        elif state['cold_rate'] is not None:
            state['slow'] = state['slow']+1 if rate > 2*state['cold_rate'] else 0
            if state['slow'] >= 2:
                if hasattr(master, '_working_rows_cache'): del master._working_rows_cache
                state.update(cooldown=3, slow=0)
        report.update(reuse_cooldown=state['cooldown'], cold_recovery=fallback,
                      cold_recovery_strategy=recovery_strategy)
        if fallback is not None: solution.seconds = perf_counter()-started
        evidence.update(rows=master.A.shape[0], columns=master.A.shape[1],
                        reused_solver=report['reused_solver'], working_rows=report['working_rows'],
                        rounds=report['rounds'], cooldown=state['cooldown'], cold_recovery=fallback,
                        cold_recovery_strategy=recovery_strategy)
        return solution, report
