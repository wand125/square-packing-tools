"""Bounded per-process phase evidence; diagnostics never change solver/proof outcomes."""
import contextlib, functools, json, os, sys, time
from pathlib import Path

_state = dict(pid=os.getpid(), argv=sys.argv[:], phases={}, active=None)
_depth = 0

def _write():
    directory = os.environ.get('SP_PERFORMANCE_DIR')
    if not directory: return
    try:
        path = Path(directory); path.mkdir(parents=True, exist_ok=True)
        _state['updated'] = time.time()
        _state['release'] = os.environ.get('SP_PERFORMANCE_RELEASE')
        totals = {k: sum(v['recent_seconds']) for k,v in _state['phases'].items()}
        total = sum(totals.values())
        _state['dominant_phase'] = max(totals, key=totals.get) if total else None
        _state['measured_share'] = {k: v/total for k,v in totals.items()} if total else {}
        tmp = path/(str(os.getpid())+'.tmp')
        tmp.write_text(json.dumps(_state)); tmp.replace(path/(str(os.getpid())+'.json'))
    except (OSError, ValueError):
        pass  # A full diagnostic volume must not abort research or certification.

@contextlib.contextmanager
def phase(name):
    global _depth
    if _depth:
        yield {}; return
    _depth += 1; started = time.perf_counter(); details = {}; error = None
    _state['argv'] = sys.argv[:]
    _state['active'] = dict(phase=name, started=time.time()); _write()
    try:
        yield details
    except BaseException as exc:
        error = type(exc).__name__; raise
    finally:
        seconds = time.perf_counter()-started
        item = _state['phases'].setdefault(name, dict(count=0, total_seconds=0., recent_seconds=[]))
        item['count'] += 1; item['total_seconds'] += seconds
        item['recent_seconds'] = (item['recent_seconds']+[seconds])[-32:]
        item['last'] = dict(seconds=seconds, error=error, **details)
        _state['active'] = None; _depth -= 1; _write()

def timed(name, function):
    if getattr(function, '_performance_timed', False): return function
    @functools.wraps(function)
    def call(*args, **kwargs):
        with phase(name) as details:
            result = function(*args, **kwargs)
            if name == 'screen':
                bad, report = result
                details.update(returned=len(bad), angles=report.get('angles_checked'),
                               unknown=len(report.get('unknown_angles',[])), nodes=report.get('nodes'),
                               periodic_full=report.get('screen_policy',{}).get('periodic_full',False))
            return result
    call._performance_timed = True
    return call
