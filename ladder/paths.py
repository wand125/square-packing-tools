"""Where the ladder, transfer and performance scripts find the solver and write results.

Solver directory (master.py, certify.py, verify.cpp, ...):
  1. $SP_SOLVER_DIR, if set;
  2. a `code/` directory next to the calling script, if present (the historical
     run-directory layout: <run>/rung.py + <run>/code/);
  3. the repository's `solver/`.

Research helpers (compare_saved.py, edge_pricing.py, residual_recovery.py, ...):
  1. $SP_RESEARCH_DIR, if set;
  2. a `research/` directory next to the calling script, if present;
  3. the repository's `ladder/`.

Results root (one sub-directory per case key):
  1. $SP_RESULTS_DIR, if set;
  2. `results/` next to the calling script when it uses the historical layout
     (a `code/` directory exists next to it);
  3. `./results` relative to the current working directory.
"""
import os
import sys
from pathlib import Path

LADDER = Path(__file__).resolve().parent
REPO = LADDER.parent


def _script_dir(script):
    if script is None:
        return None
    p = Path(script).resolve()
    return p if p.is_dir() else p.parent


def solver_dir(script=None):
    if os.environ.get('SP_SOLVER_DIR'):
        return Path(os.environ['SP_SOLVER_DIR']).resolve()
    d = _script_dir(script)
    if d is not None and (d/'code').is_dir():
        return d/'code'
    return REPO/'solver'


def research_dir(script=None):
    if os.environ.get('SP_RESEARCH_DIR'):
        return Path(os.environ['SP_RESEARCH_DIR']).resolve()
    d = _script_dir(script)
    if d is not None and (d/'research').is_dir():
        return d/'research'
    return LADDER


def results_root(script=None):
    if os.environ.get('SP_RESULTS_DIR'):
        return Path(os.environ['SP_RESULTS_DIR']).resolve()
    d = _script_dir(script)
    if d is not None and (d/'code').is_dir():
        return d/'results'
    return Path.cwd()/'results'


def resolve_input(path, *bases):
    """An input named in a config: absolute as given, else the first base where it exists
    (callers pass the config's directory first, then the script's directory)."""
    p = Path(path)
    if p.is_absolute():
        return p
    for base in bases:
        if (Path(base)/p).exists():
            return Path(base)/p
    return Path(bases[0])/p if bases else p


def use_solver(script=None):
    """Put the solver (and the research helpers) on sys.path; returns the solver directory."""
    code = solver_dir(script)
    research = research_dir(script)
    for d in (research, code):
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    return code
