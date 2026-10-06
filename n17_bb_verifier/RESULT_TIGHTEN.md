# v3 tighten verification results

Implemented on branch `tighten-v3`, starting at `bfabaab`. No push was made.

## Changes

- `src/tighten.rs`: exact alive-set subtraction and coverage; trig-key checks; pair and wall elimination replay; conservative modulo-2π family filtering; cross-product interior-maximum exclusion; mandatory fixed window directions; tighten containment and angle closure.
- `src/nodes.rs`: schema-aware dispatch, v3 Taylor rejection, replay using recomputed final boxes, and v3-only application of bounds when `next` is absent. V1 retains its prior behavior.
- `src/main.rs`: v3 header/tree checks, one-child tighten transitions, angle-leaf structure, and optional summary count validation.
- `src/compact.rs`: retain interned metadata and streaming node checks; omit E from retained tighten metadata because replay loads it from the node chunk. V1 storage is unchanged, and trig keys are retained only for v3.
- `tests/cli.rs`, `tests/fixtures/v3-*`: two tiny synthetic whole-tree certificates and eleven corruptions; custom synthetic cells and digest verification. `scripts/make_v3_fixtures.py` rebuilds these fixtures.
- `scripts/check_v3.py`, `scripts/measure.py`, `scripts/check_v1.py`: external certificate, tamper, receipt, peak-RSS, and backward-compatibility checks. Large inputs remain outside the repository and were read only.
- `README.md`: v1-only provenance claim, local v3 specification and its authorship, upstream limitation, independent second-system checker, semantics, commands, and measurements.

## Validation

- `cargo test --locked`: **19 unit tests + 4 CLI tests passed**, including all original 14 unit and 2 CLI tests. New tests cover exact endpoint ownership, singleton removal, wrapped families, mandatory window ends, strict touching rejection, successful wall replay, and bounds without `next`.
- `cargo clippy --all-targets -- -D warnings`: **PASS**. Lint configuration is unchanged; no `unsafe` or floating-point geometric decisions were introduced.
- `cargo fmt --check` and `git diff --check`: **PASS**.
- Rebuilt the original `bfabaab` binary entirely under `target/` and compared all seven retained v1 fixture receipts: every field agrees after removing only `seconds`. See `results/tighten/v1-agreement.json`.
- Ran all thirteen synthetic fixtures through the Python first system using Python 3.14 with bytecode writing disabled: two PASS and eleven FAIL, all verdicts agree. Both passing receipts agree field by field. See `results/tighten/synthetic-agreement.json`.
- Full A/C1/C2 runs at one and four threads: all **PASS**, all six receipts agree with the supplied Python first-system receipts. Comparison excludes timing and provenance/context fields (`seconds`, `directory`, `provenance`, `cells_source`, `sample`); no verification fields or counters are excluded. The latter two context fields were already absent from v1 Rust receipts.

## Full-certificate measurements

Elapsed seconds / peak resident MiB (1 MiB = 2²⁰ bytes). Rust ran on the local shared ARM macOS host; Python values come from supplied Linux receipts and GNU time logs. These are cross-machine observations, not a controlled speedup benchmark. RSS is measured for each Rust child in a fresh helper process using `getrusage(RUSAGE_CHILDREN)`; the helper is excluded. macOS `time -l` cannot query `kern.clockrate` inside the sandbox, so it was not used for the retained measurements.

| Certificate | Python, one process | Rust, one thread | Rust, four threads |
| --- | --- | --- | --- |
| A | 661.313 s / 513.13 MiB | 67.954 s / 74.89 MiB | 27.871 s / 85.91 MiB |
| C1 | 976.651 s / 742.38 MiB | 90.938 s / 106.89 MiB | 30.863 s / 127.84 MiB |
| C2 | 674.437 s / 549.64 MiB | 87.499 s / 71.47 MiB | 24.790 s / 82.97 MiB |

The supplied Python times round to the task’s 661 / 977 / 674 seconds. Retained Rust receipts, per-process usage records, source Python receipts, and machine-readable measurements are under `results/tighten/`.

| Certificate | Nodes | Leaves | Tighten nodes | Angle leaves | Depth | Pair eliminations | Wall eliminations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 6293 | 2314 | 1921 | 639 | 26 | 23319 | 0 |
| C1 | 8485 | 3025 | 2762 | 897 | 41 | 32436 | 896 |
| C2 | 7154 | 2651 | 2151 | 607 | 25 | 26275 | 279 |

## Tampering

All six full external tamper runs **FAIL at the expected check**. The source remote tamper receipts were unavailable as noted in the task, so expected messages are the six task-provided Python results. These are full runs of 6,293 nodes each, not samples.

| Tamper | Rust failure(s) |
| --- | --- |
| `drop_partner_interval` | `node 23: E: partner intervals do not cover alive set` |
| `pair_as_wall` | `node 23: E: wall elimination not proved` |
| `widen_eliminated` | `node 23: E: pair elimination not always overlapping` |
| `angle_not_empty` | `node 23: E: angle closure has no empty alive set` |
| `wrong_pair_index` | `node 23: E: invalid elimination pair` |
| `drop_window` | `T2: node 22 angle split children mismatch`; `node 23: P2: pieces do not cover normals` |

## Interpretation and conservative choices

- Followed proposal sections 1, 2, and 3.5 and the exact Python reference. Tighten containment is non-strict (`A′ ⊆ A`), matching the executable reference and task summary; unchanged intervals are permitted.
- Replay uses the node’s own recomputed boxes, not its parent’s boxes or a potentially wider recorded final. For no-`next` rounds, v3 uses the exact verified bound assignments without substituting the clipped-cell box, matching the Python extension.
- Closed interval removal owns both endpoints. Partner coverage refers to the current alive set before that elimination, and strict overlap/wall inequalities reject mere contact.
- Families are excluded only when exact rational modulo bounds prove disjointness. More than sixteen candidate turn steps conservatively retain the family, exactly as the reference does. Turns use arbitrary-size integers. If the sign tests cannot rule out an interior maximum, use the outward square-root bound.
- Both fixed window endpoints are mandatory independently of the retained families. This accommodates a separating direction anywhere in the window.
- Counts are not invented: the Python reference exposes tighten/angle totals through `counts.tighten_split_ok`, `counts.closed_angle_ok`, and `reasons.angle`, rather than new top-level receipt fields. Optional manifest summary values are validated separately.
- Failure messages preserve the reference phrases with this verifier’s node/check prefixes (`E`, `T2`, `B2`, `schema`). For a malformed tighten child, Rust says `T2: ... tighten split children mismatch`; the reference’s reused base formatter says `pair split children mismatch`. Both identify the same T2 transition failure. The six requested external tamper cases use their specified checks.

## Reproduction

On this ARM Homebrew host:

```sh
export CPATH=/opt/homebrew/opt/gmp/include
export LIBRARY_PATH=/opt/homebrew/opt/gmp/lib
cargo build --locked --release
cargo test --locked
cargo clippy --all-targets -- -D warnings
cargo fmt --check
python3 scripts/check_v3.py
python3 scripts/check_v1.py target/baseline-build/release/n17bb-verify
```

The baseline binary must first be built from `bfabaab`; it is intentionally not committed. `--data PATH` selects another read-only external dataset root for `check_v3.py`.

## Commits

- `d9fc024`: exact v3 implementation.
- `0856c97`: regression fixtures, tests, and verification scripts.
- Final documentation/results commit contains this report and the retained evidence.

The supplied untracked `TASK_TIGHTEN.md` is left untouched. All edited content is inside this worktree; committing necessarily updates its linked Git metadata in the owning repository. No other worktree content was modified.
