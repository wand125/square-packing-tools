# Working-LP runtime

A common entry point for new rectangle searches, so that they do not copy an old
implementation and reintroduce the same performance problems. It replaces
`Master.solve` with a managed working-row LP and records per-phase timings. Rung,
pricing, model and proof logic are unchanged.

## Local use

Run a ladder script through the wrapper:

```sh
python performance/runtime/runtime_wrapper.py ladder/rung.py <case key> <config.json>
```

The wrapper finds the solver as described in `ladder/paths.py` (`SP_SOLVER_DIR`, else
`code/` next to the entry script, else `solver/`), puts this directory on `sys.path`
(`runtime_solver.py`, `working_rows.py`, `runtime_metrics.py`), installs the managed
solve on `Master`, and runs the entry script unchanged.

To combine it with the batch16 screen policy (see `../screen_policy/README.md`):

```sh
PYTHONPATH=performance/screen_policy SP_SCREEN_POLICY=batch16 \
  python performance/runtime/runtime_wrapper.py ladder/rung.py <case key> <config.json>
```

- Do not use the wrapper for explicit all-IPM or initial-IPM jobs (`continue_ipm: true`
  or `initial_solver: "ipm"`); run `ladder/rung.py` directly for those.
- Solves with point atoms or with extra arguments call the original solver.
- Phase metrics are written to `$SP_PERFORMANCE_DIR/<pid>.json` (default
  `./performance_metrics`).
- Unless the config sets `screen_audit_batch` to something other than 16, the wrapper sets
  `SP_SCREEN_AUDIT_BATCH=16` and `SP_SCREEN_WITNESS_DIR=<results root>/<case>/witness-archive`
  (both only if not already set). Set `screen_audit_batch: 0` in the config, or
  `SP_SCREEN_AUDIT_BATCH=0`, to opt out.
- To disable the runtime, run the entry script directly without the wrapper.

## Controls

- The solver and basis are reused only after an exact check that the matrix prefix matches.
- The working model is rebuilt when the working row count exceeds `max(4096, 2 * columns)`.
  All finite rows are retained.
- A RuntimeError during reuse is retried once cold on the same full-row model. A cold failure
  propagates.
- A RuntimeError on the first solve without saved row-selection hints is retried once cold,
  with the newest 16 rows as the initial candidates. Solves that start with nonzero
  row-selection hints, and invalid input, are not retried.
  A failed partial solution is never returned; only solutions whose coverage over all finite
  rows, dual constraints and gap were checked are returned.
- If a managed solve fails inside the wrapper, that Master falls back to the original solver
  for the rest of the run. The original residual recovery and native model signature are kept.
- If time per nonzero exceeds twice the observed cold rate twice in a row, the next 3 solves
  are cold and the rate is re-evaluated. This is a heuristic to avoid slowdowns, not a
  guarantee of always being fastest.
- Full-row coverage, dual constraints, gap, nonnegativity/rescaling and the conditions of the
  independent proof are unchanged.

## Metrics

With the screen-policy import hook active, LP, matrix construction, counterexample search,
pricing and independent verification are timed. Each process writes
`$SP_PERFORMANCE_DIR/<pid>.json` atomically, with the current phase and its start time, and
for each phase the latest 32 durations and the cumulative time. A failure to write metrics
never stops a search or a proof. Shares are computed within each phase's latest (at most 32)
measurements; they are neither CPU time nor shares over an identical time window. The wall
time of independent verification includes any wait for a verification slot.

This is not a mechanism that automatically applies unknown algorithms to new bottlenecks. It
shares verified improvements, suppresses wasted rebuilds, provides fallbacks and records
measurements.

## Tests

```sh
python -m pytest performance/runtime
```

`test_runtime.py` checks the real LP, model invariance, the original native signature, the
fallback on failure, backoff on slowdown, and the bounds and failure handling of metrics.
`test_working_rows.py` checks the working-row LP itself.

## Full-angle audit batching

With the wrapper, new and continued jobs default to `screen_audit_batch: 16`. The full-angle
audit every 8th screen is kept; every counterexample is saved to a durable NPZ first and then
admitted to the LP 16 rows at a time. Pending counterexamples are re-evaluated under the
current weights and support, and the most violated are chosen first. Running out of pending
counterexamples is never by itself treated as a full-net pass; a fresh search is run. On a
restart, pending counterexamples are not treated as passed; a fresh search is run. Finite LP
rows already saved are never deleted.
