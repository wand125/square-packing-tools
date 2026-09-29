# square-packing-tools

Tools for proving **lower bounds** on `s(n)`, the side of the smallest square that holds `n`
unit squares, with rectangle-density certificates. They are the drivers we used to produce
the certificates published in
[wand125/square-packing-bounds](https://github.com/wand125/square-packing-bounds).

The method and the certificate format are tokoharu's
([tokoharu/square-packing-density-bounds](https://github.com/tokoharu/square-packing-density-bounds)).
What this repository adds is the machinery around his solver: moving a certificate to a
larger `n` or a larger `L`, recovering budget when a rung stalls, and making each LP rung
faster. Every certificate is still accepted only by his unchanged verifier (`solver/verify.cpp`).

It covers three areas:

1. **Moving in `n` and `L`**: `transfer/`, `ladder/`
2. **Speed**: `performance/`
3. **Exact checks of point and threshold-charge certificates**: `general_pose_tree/`

## Layout

```
solver/        tokoharu's LP solver as we run it, plus our modules (see solver/PROVENANCE.md)
ladder/        one rung of a ladder: rung.py (next rung / transfer), edge_rung.py (budget recovery)
transfer/      write rung configs: make_transfer.py, make_edge.py; l_cap.py, next_step.py
performance/   runtime/        working-row LP with basis reuse, per-phase timings
               screen_policy/  batch-16 counterexample screen, angle-parallel screen
               verifiers/      cached-axis variant of the verifier (search time only)
               point_verifier_lazy/  faster zmx2 for point certificates (patch on evand's verifier)
general_pose_tree/  exact branch-and-bound checks for point / threshold-charge certificates (standard library only)
tests/         smoke and end-to-end tests
```

## Install

Python 3.10+ and a C++ compiler (`g++`) for the verifier.

```sh
pip install -r requirements.txt
python -m pytest -q                       # quick tests
SP_SLOW_TESTS=1 python -m pytest -q tests # + a tiny end-to-end ladder (about a minute)
```

The end-to-end test certifies `n=3` at `L=1.5`, transfers it to `n=4` at `L=1.6`, and runs a
budget-recovery rung at `L=1.55`, all through the commands below.

## Moving a certificate

A *rung* takes a certified parent, re-optimizes a rectangle measure at the target `(n, L)`,
screens it against all placements, and proves it with the independent verifier. The parent is
only a starting point: its weights are never inherited as a proof.

**To a larger `n` (transfer), or to the next `L`:**

```sh
python transfer/make_transfer.py <parent proof dir> --parent-n 29 --target-n 30 --L 5.87 --key n30_L587
python ladder/rung.py n30_L587 rungs/n30_L587.json
```

The budget is `target_n - 1/100`. Results, including `progress.json` and the proof directory,
go to `./results/<key>/` (`SP_RESULTS_DIR` overrides).

**Budget recovery** when a rung stops over budget: start from the rung's saved rows and columns,
price first with 4-edge moves, then screen, repair and prove.

```sh
python transfer/make_edge.py results/<key>/ --n 29 --L 5.79 --key n29_edge --pricing-rounds 3
python ladder/edge_rung.py n29_edge rungs/n29_edge.json
```

With `--source-L`, the saved rectangles are first scaled by `L / source_L` (start lower,
recover budget, then climb).

**Choosing `L`:**

- `python transfer/next_step.py <certificate dir>` suggests the next `L` from the budget
  headroom a certified rung left. It is a heuristic, not a bound.
- `python transfer/l_cap.py <n>` prints `L_cap(n)`, a **search ceiling (a guide, not a proven
  bound)** above which a rectangle certificate for `n` should not be attempted. `UB(n)` is the
  side of a known packing, `B = 0.9977` the core side and `D = 83/40000` the verifier's net
  parameter. For a witness whose orientations lie on the verifier's 201-angle net (such as the
  axis-parallel `k × k` grid behind an integer `UB(n) = k`), the ceiling is `B·UB(n)`. In
  general it is `α·UB(n)` with `α = B(1 + D) = 399908091/400000000`. `UB(n)` in
  `transfer/data/ub.json` is rounded for display, which is one more reason to treat the result
  as a guide. Where its `ubExact` is an integer that differs from `ub`, that integer is only a
  coarse upper bound `⌈√n⌉`, not the side of a known packing.

`transfer/scale_and_verify.py` scales a running search's current candidate to the budget
(`n - 1/100` by default; any target at or above `n` is refused) and sends it to the verifier, without disturbing the search. If the proof goes through,
the rung can be skipped.

## Speed

Each component can be switched off, and none of them changes the target, the budget, the
interval arithmetic, the LP residual checks, or the independent proof.

- **Working-row LP** (`performance/runtime/`): the LP is solved on a working subset of rows,
  and the solver and basis are reused when the matrix prefix is exactly unchanged.
  Run a rung through `python performance/runtime/runtime_wrapper.py ladder/rung.py ...`.
- **Batch-16 screen** (`performance/screen_policy/`): return to the LP after 16
  counterexamples, with a periodic full-angle audit. The certifying pass still requires all
  201 angles.
  Enable with `PYTHONPATH=performance/screen_policy SP_SCREEN_POLICY=batch16`.
- **Angle-parallel screen** (same directory): identical results on several threads.
  Enable with `SP_PARALLEL_SCREEN_THREADS=<n>`.
- **Cached-axis verifier** (`performance/verifiers/`): used during search only. Published
  certificates are checked with the canonical verifier.
- **Lazy zmx2** (`performance/point_verifier_lazy/`): a patch on Evan Daniel's point verifier.
  It builds from a source you supply and refuses any other version. Recommended for point
  certificates only.

Each directory's README gives the exact conditions and the reported speed-ups. These are
measurements from our runs, not guarantees.

## Exact checks for point and threshold-charge certificates

`general_pose_tree/` generalizes the branch trees and wall enclosures of our point-only
`n = 21` verifier (published in square-packing-bounds) to any `n`, rational `L`, and measures
made of weighted points plus k-of-m threshold features. It is pure Python with exact
arithmetic. As a test, it independently rechecked all 12,028 per-row core scans of
Kleddamag's `n = 11` certificate (`s(11) > 31/8`) and found identical minima. It rechecks the
row scans only; the global counting argument is Kleddamag's. See `general_pose_tree/README.md`.
Kleddamag's certificate is read from his repository and is not included here.

## What is a proof here

For rectangle certificates, only the verifier's acceptance is a proof. That means `solver/certify.py` compiling and running
`solver/verify.cpp`, byte-identical to tokoharu's (SHA-256 `a75140df…`, the verifier the
published certificates were checked with).
The LP, the screens and every speed-up only propose candidates.

## Attribution

Developed by wand125 with OpenAI Codex (rectangle ladder, working LP, performance runtime) and
Anthropic Claude (orchestration and job tooling), on top of tokoharu's
square-packing-density-bounds (MIT). The rectangle-density method, the LP solver and the
verifier are tokoharu's; `solver/PROVENANCE.md` lists file by file what is his, what we
modified, and what we added.

## License

MIT (see `LICENSE`). Third-party code and its licenses: `THIRD_PARTY_NOTICES.md`.
