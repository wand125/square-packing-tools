# general_pose_tree

Exact, pure-Python checks for charge certificates of square-packing lower bounds, generalised from the
point-only n = 21 verifier (lemmas PL30/PL43/PL48 wall enclosure and PL45–PL47 predicate branch trees)
to any `n`, rational container side `L`, parent side `A`, core side `B`, and a measure made of ordinary
weighted points plus k-of-m threshold features.

| Module | What it checks |
|---|---|
| `measure.py` | Measure = weighted points + threshold features (charge `w` when a closed core holds at least `k` of `m` sites; budget `floor(m/k)·w`). Exact total budget, D4 invariance, direct and signed inclusion–exclusion evaluation. Loader for Kleddamag's JSON format. |
| `enclosure.py` | For a row `[a, b, t, B]`: the exact centre domain `[r, L−r]^2` of side-`A` parents with half-angle in `[a, b]` (no interior minimum of `cos+sin`, proved by the sign of `u²+2u−1`), strict containment of the side-`B` core in every such parent, and contiguous angle coverage of all rows. |
| `branch.py` | `RowSolver.minimize`: exact minimum of the core charge over every centre of one row (best-first branch and bound in the integer core frame, exact surely-in / surely-out classification, open-cell enumeration at leaves; boundary handled by upper semicontinuity). `RowSolver.certify(target)`: proves minimum ≥ target. Returns node counts and an exact witness centre, which is replayed by direct evaluation. |

All accepted inequalities are integer or `Fraction` comparisons; floats only order the search.

## Verified so far (reported values)

- Tests: `tests/` (10 cases): brute-force minima on synthetic rows with features, classification soundness on
  random rational centres, budget pigeonhole on random disjoint assignments, D4 checks, and agreement with the
  independent point-only fixed-angle separator on random inputs.
- n = 21 point cover (4,604 points, L = 5): exact minima at four angles equal those of the existing
  fixed-angle separator.
- n = 11, Kleddamag's `11-squares-certified-bound` (commit `6a733f3`, `s(11) > 31/8`): all 12,028 rows
  checked; every row's exact minimum equals the recorded `minimum_units`, the histogram is identical, the global
  minimum is `999962528` (= their Γ), and all witnesses replay. Enclosure: rows contiguous from 0 past √2−1,
  minimum strict core margin `1/10^12`. 9,446 CPU seconds; median 3,464 boxes expanded per row (max 6,676).
  This rechecks the per-row core scans only; the global counting argument (D4 folding, budgets, `11Γ > M`)
  is Kleddamag's and was not re-proved here, although the budget `M` and D4 invariance were recomputed.

## Run

```sh
python -m pytest -q tests   # SP_BOUNDS_REPO=<square-packing-bounds checkout> enables the separator comparison
python check_n21.py <square-packing-bounds checkout> out.json 0 1/10 2/5 1/1000   # n = 21 cross-check
python run_n11.py <kleddamag-repo> out.jsonl 0-12027   # resumable; ROWSPEC like 0-99,120,300-310
python summarize_n11.py
```

Needs Python 3.12+; `run_n11.py` and the tests use only the standard library plus `pytest`.

Attribution: the n = 11 certificate and its format are Kleddamag's (see that repository's licences and
notices); this code only reads it.
