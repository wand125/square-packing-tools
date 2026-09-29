# Provenance of `solver/`

This directory is the rectangle-density LP solver as it runs in our production ladders
(snapshot of the solver directory of our budget-recovery ladder, trimmed to what `ladder/` imports).

Upstream: [tokoharu/square-packing-density-bounds](https://github.com/tokoharu/square-packing-density-bounds)
(MIT), compared against commit `84bebef51856d46a19c145b035664324ba9572d3`.

| file | status |
|---|---|
| `advance.py` | upstream, unchanged |
| `certify.py` | upstream, unchanged |
| `fast_geometry.py` | upstream, unchanged |
| `plot_solution.py` | upstream, unchanged |
| `pricing.py` | upstream, unchanged |
| `refinement.py` | upstream, unchanged |
| `run_verify.py` | upstream, unchanged |
| `verify.cpp` | upstream, unchanged (the independent verifier; certificates are checked with this file) |
| `geometry.py` | upstream, modified |
| `master.py` | upstream, modified (point atoms as extra columns, residual-failure capture to `$SP_RESIDUAL_DUMP_DIR` or `./captures`) |
| `axis_screen_fast.py` | ours |
| `global_separation_fast.py` | ours |
| `net_screen_scratch.py` | ours |
| `overlap_scratch.py` | ours |
| `points.py` | ours |
| `rectangle_rescue.py` | ours |
| `residual_dump.py` | ours |

`patches/` holds `diff -u` of each modified file against the upstream commit above.
