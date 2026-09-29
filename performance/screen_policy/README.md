# Batch-16 screen policy for rectangle searches

An import hook (`sitecustomize.py`) that wraps only the rectangle
`global_separation_fast.separate_global` in newly started Python processes. The original
files are not modified.

- Normally the screen returns to the LP after 16 counterexamples. A smaller limit requested
  by the caller is respected.
- Recent counterexample directions are tried first. On the first call the directions are
  recovered from the last 256 saved rows.
- Every 8th call on the same Master is a full-angle search (max_rows at least 1,000,000).
- If a call returns no counterexample while angles remain unscanned or unknown, a full-angle
  search is run immediately as well.
- Returning `SCREENED_ALL_NET_CENTERS` requires all 201 angles, no unknown angle and no
  counterexample.
- The target, the search node budget, the interval arithmetic, the LP residual checks and the
  independent proof are unchanged.

`report['screen_policy']` records the call number, periodic audits, full searches triggered by
an empty result, and the effective limit. The run log shows `screen_policy_enabled` at start.

## Enabling and disabling

Put this directory on `PYTHONPATH` and set `SP_SCREEN_POLICY=batch16`:

```sh
PYTHONPATH=performance/screen_policy SP_SCREEN_POLICY=batch16 \
  python ladder/rung.py <case key> <config.json>
```

Without these variables (or with `SP_SCREEN_POLICY=full`) the original screen is used.
Always use the original screen when measuring the baseline in a comparison.

The hook also times the LP, geometry, pricing and proof phases (`runtime_metrics.py`,
written to `$SP_PERFORMANCE_DIR`, default `./performance_metrics`).

The code never rewrites an unknown function signature silently; it raises an error at import
time instead. The supported signature is
`(master,solution,target,budget,max_rows,preferred_angles)`.

## Angle-parallel screen

`parallel_screen.py` runs the 200 oblique net angles of `separate_global` on a thread pool
(a `nogil` compilation of the same `verify_angle`), consuming results strictly in the original
order, so witnesses, node counts and status are identical; only wall-clock time changes. It is
loaded by the hook above and enabled with `SP_PARALLEL_SCREEN_THREADS=<threads>`
(`SP_PARALLEL_SCREEN=0` disables it). It applies only when the SHA-256 of `inspect.getsource(separate_global)` is in `KNOWN`
(`48846bab...`, which `solver/global_separation_fast.py` in this repository matches); otherwise
it logs `parallel_screen_skipped` and the original function runs.

- Bit-identity relies on `verify_angle` being a pure function and on recompiling it with
  numba as `njit(nogil=True)(py_func)`.
- Without `SP_PARALLEL_SCREEN_THREADS` it is off (sequential).
- Reported: on Linux with numba 0.67, six real candidates (n=28 and n=61) gave identical
  results, 4.1-5.9x faster. On macOS (Apple Silicon) it runs but speed was not measured.
- The screen is a numerical sieve for the LP, not a proof; certificates are proved separately
  by the independent 201-direction verifier.

## Tests

```sh
python -m pytest performance/screen_policy
```

Evidence for adoption: on n41 L6.755 the search took 19.5 min versus 54.7 min (2.81x), and
both methods produced an independent proof. The same speed-up is not guaranteed for every
input.

## Splitting the admission of full-angle audit counterexamples

Active only in jobs that set `SP_SCREEN_AUDIT_BATCH=16` explicitly (the runtime wrapper in
`../runtime` sets it by default). The full-angle search is kept; when more than 16
counterexamples come back, all of them are saved (fsync) to an NPZ first and only 16 are
returned to the LP. The rest are re-evaluated for coverage under each new solution, and at
most 16 still-violated ones are returned. Even when all pending counterexamples are resolved,
a fresh search is run before deciding. A pending batch never returns a full-angle pass.

The archive location is `SP_SCREEN_WITNESS_DIR`, then `SP_RESIDUAL_DUMP_DIR`, and finally
`witness-archive/` under this directory. Each file records all counterexamples and the
original search report. If saving fails, splitting does not continue. On a process restart
the pending queue is not restored automatically; a fresh search and full-angle audit are
required.
