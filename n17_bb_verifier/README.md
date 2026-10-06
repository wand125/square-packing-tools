# n17-bb-verifier

`n17bb-verify` is an exact verifier for the n = 17 sub-pattern branch-and-bound certificates of the [squares project](https://github.com/jlevy/squares) (interval schemas `n17-subpattern-bb-certificate/v1` and `/v3`).
It decides the same question as the project’s standing verifier, `packing/devtools/verify_n17_bb_certificate.py`:

> Does the certificate prove that no k unit squares, square s centred in cell s at any angle, all inside the container, can have pairwise disjoint interiors?

It is a second implementation of the same checks, not a different proof.
It exists because the standing verifier is slow and memory-hungry on large trees.
On the 194,328-node certificate below it takes 173 seconds and 1.0 GB with four threads, against 98 minutes and 11.1 GB for the standing verifier in one process.

## What it checks

The checks are those of the standing verifier, under the same names. The certificate’s own `README.txt` lists them too.

| Check | What is verified | Where |
| --- | --- | --- |
| Header | the cell polygons equal the declared cover (exactly or by SHA-256), pairs, root angles and boxes, the π/2 multiples | `check_header` in `src/main.rs` |
| Trig | every recorded cos/sin enclosure contains the true value: 160-bit fixed-point Taylor sums with outward Lagrange remainder, retried at 2400 bits | `check_trig`, `cos_sin_bits` in `src/exact.rs` |
| T1–T3 | one root with the root angles and no windows; children partition their parent; every node is reached once; closed nodes are leaves; open nodes have a split and final boxes | `check_tree` |
| B1–B2 | round-0 boxes contain the wall contraction clipped to the cell; each next box and the final box contain the recomputed ones | `check_node_inner`, `contract` |
| P1–P4 | the gap lower bound; the angle pieces cover every normal modulo 2π inside the window; the three-plane and one-plane relaxations; pair splits leave no possible piece uncovered | `pair_planes`, `pieces_cover`, `piece_planes`, `check_open` |
| C1–C5 | disc and pair closures; each cut row is valid over the exact plane minimum; the Farkas combination is positive (LP closure); each bound tightening is valid in order; `obbt` emptiness | `check_closed_pair`, `row`, `combination`, `check_bounds` |

All arithmetic is exact: GMP integers and rationals through [`rug`](https://crates.io/crates/rug), with the trigonometric recurrence kept in integer form until the enclosure endpoints become rationals.
π is enclosed with Machin’s formula.
Critical multiples of π/2 are located by exact interval division.
Floating point is used only to report elapsed time.

The receipt has the standing verifier’s fields: status, node and leaf counts, maximum depth, closure reasons, the per-check counters, failures, and seconds.
The counters match the standing verifier’s exactly, including on certificates that fail.

## How it was written, and how independent it is

The v1 part was written from the standing verifier and the certificate format’s README, as a specification.
For that v1 work, the generator, the native Rust producer, the hull kernel and the selector were not read or reused.
The Rust implementation shares no code with the standing verifier, and it depends on no code from the squares repository.

The v3 `tighten` / `closed: "angle"` extension is a specification added by us, not upstream. It was written by the author of the propagation prover; the upstream verifier does not check it. This implementation follows that specification and its Python first-system reference, `verify_n17_bb_tighten.py`. The v1 claim about development without reading the producer does not describe the provenance of this extension. An independent second-system checker also exists, written only from the specification by another author.

It is not independent of its author.
The same contributor, working with an AI coding agent, also wrote the native Rust producer that generates some of these certificates (squares PR #350).
Its value as a cross-check is that it shares no code with either side, and that its receipts agree with the standing verifier’s on every check counter.

## Results

The standing verifier ran unchanged in full mode, in one process, on a separate 8-vCPU Linux host (AMD EPYC 7B13).
Receipts for both are in [`results/`](results/), with local paths removed.

| Certificate | Nodes | Standing verifier | This verifier | Receipts agree |
| --- | --- | --- | --- | --- |
| Pattern A (6 interior cells) | 41,958 | PASS, 1,287 s | PASS, 91 s, 3 threads | every field and counter |
| side-S0, side-N0 + 5 interior cells (B2 rule) | 194,328 | PASS, 5,906 s, 11.1 GB | PASS, 173 s, 4 threads, 1.0 GB | every field and counter |
| side-S0, side-W0 + 5 interior cells (B2 rule) | 79,396 | PASS, 2,220 s, 4.3 GB | PASS, 68 s, 4 threads, 0.45 GB | every field and counter |

The A run of this verifier was on a shared Apple M4 host. The other two were on the Linux host.

Further certificates will be added here as they are checked.

## Build and run

Rust 1.98.0 is pinned in `rust-toolchain.toml`. Building needs GMP’s headers and library (`libgmp-dev` on Debian and Ubuntu, `brew install gmp` on macOS). On ARM Homebrew installations, set `CPATH=/opt/homebrew/opt/gmp/include` and `LIBRARY_PATH=/opt/homebrew/opt/gmp/lib` if the compiler otherwise finds an older or Intel GMP.

```bash
cargo build --locked --release
./target/release/n17bb-verify CERTIFICATE_DIR --threads 4 --output receipt.json
```

The exit status is 0 for PASS, 1 for FAIL and 2 for an invocation or output error.
The receipt goes to stdout, and also to `--output` when given.

- `--threads N` sets the worker threads; the default is 1.
- `--cells FILE --cells-sha256 DIGEST` checks against an external cell file. The default is the squares project’s capacity-one cover, embedded from `tests/cells.json`.
- `--manifest NAME` overrides the manifest named on the last line of the certificate’s `README.txt`.
- `--node-ids FILE` checks only the listed nodes, after checking the whole tree and all trigonometry. The receipt is then marked `mode: sample` and does not stand for full verification.

It reads the certificate in two streaming passes, one gzip chunk at a time.
The first pass keeps compact tree metadata, with repeated JSON subvalues interned in an arena; the second checks nodes in parallel.
Memory grows with the number of nodes, not with the size of their records.

## The v3 extension

Run v3 with the same CLI, using `--manifest NAME` when its directory has no `README.txt`:

```bash
./target/release/n17bb-verify ../joint_tools/runs/cert3/A \
  --manifest 6633f10e5e9e66783a495dc9e12961c089c78b99c855bbe4eeb0e2cfd8840240 \
  --threads 4 --output receipt.json
python3 scripts/check_v3.py
```

The external-data script runs A/C1/C2 at one and four threads, compares receipts with the Python first system, and rejects all six external tamper cases at their expected checks. Use `--data PATH` to locate another `joint_tools` directory. The large certificates are not fixtures.

A `tighten: [E, A′]` split has one child with the specified narrower angles and unchanged windows. An `angle` leaf records its elimination list in `angle`, has no split, and must empty at least one angle set. Both replay E against the node's recomputed final boxes; recorded final boxes must contain those boxes. In v3, verified bounds are applied even when a round omits `next`; v1 retains its original behavior.

Replay tracks finite unions of rational intervals with exact endpoint ownership: deleting a closed interval also deletes its endpoints. Pair eliminations require the partner intervals to cover the partner's current alive set and prove strict overlap on every listed interval pair. Wall eliminations prove that the final box misses the angle-dependent wall box. Every elimination endpoint must be a trig-table key. After a tighten replay, each remaining set must fit inside the child's angle interval.

Overlap checks use the eight edge-normal families, conservatively filtered modulo 2π. An endpoint maximum is used only when exact cross-product sign bounds exclude an interior maximum; otherwise the existing outward square-root bound is used. Both window ends are also checked as fixed directions, so a separating direction anywhere in the window is covered, not just an edge normal. All geometric decisions use exact rationals and outward enclosures.

Tighten children count as ordinary nodes; angle closures count as ordinary leaves. Optional manifest `tighten_nodes` and `angle_leaves` summaries are checked. Receipts retain the Python reference's fields: these totals appear as `counts.tighten_split_ok`, `counts.closed_angle_ok` and `reasons.angle`, with elimination counts under `counts`. E is streamed with node records and is not retained in the interned tree metadata.

Benchmark results (elapsed time / peak RSS) are recorded in `results/tighten/` and `RESULT_TIGHTEN.md`.

| Certificate | Python, 1 process | Rust, 1 thread | Rust, 4 threads | Receipt agreement |
| --- | --- | --- | --- | --- |
| A | 661.313 s / 513.13 MiB | 67.954 s / 74.89 MiB | 27.871 s / 85.91 MiB | Every verification field and counter |
| C1 | 976.651 s / 742.38 MiB | 90.938 s / 106.89 MiB | 30.863 s / 127.84 MiB | Every verification field and counter |
| C2 | 674.437 s / 549.64 MiB | 87.499 s / 71.47 MiB | 24.790 s / 82.97 MiB | Every verification field and counter |

Python timings and peak RSS come from the supplied first-system Linux receipts and GNU time logs; Rust is measured locally on an ARM macOS host. These are shared-host, cross-machine observations rather than controlled speedup measurements.

## Tests

```bash
cargo test --locked
cargo clippy --locked --all-targets
cargo fmt --check
# Optional comparison with a saved pre-v3 binary:
python3 scripts/check_v1.py /path/to/pre-v3/n17bb-verify
```

- V3 tests include whole one-node angle and two-node tighten certificates, eleven tampered variants, closed-endpoint subtraction, singleton sets, modulo wrapping, strict touching rejection, mandatory window ends, and bounds without `next`. Rebuild the synthetic fixtures with `python3 scripts/make_v3_fixtures.py`.
- Unit tests cover exact rational endpoints exported from the standing verifier at positive and negative angles, signed critical-angle boundaries, clipping, square-root bounds, and tree partitions.
- `tests/cli.rs` runs the binary on `tests/fixtures/small-certificate`, a complete 83-node certificate, and on six corrupted copies of it. Each copy must be rejected at its check:

  | Copy | Change | Rejected at |
  | --- | --- | --- |
  | `mutated-multiplier` | one Farkas multiplier made negative | C3/C4 |
  | `mutated-bound` | one tightened bound raised far above its value | C4 |
  | `mutated-cut` | one cut’s right side raised far above its value | C2 |
  | `mutated-split` | one angle split point moved outside its interval | T2 |
  | `mutated-drop-leaf` | one closed leaf removed | T2 |
  | `mutated-narrow-final` | one open node’s final box narrowed | B2 |

CI builds and tests on Ubuntu 24.04 with every push.

## Limits

- Only non-Taylor interval schemas v1 and v3 are supported. Taylor certificates and Taylor metadata in v3 nodes are rejected.
- It verifies a certificate against a cover; it does not check that the cover’s cells have capacity one or that the cover is complete. Those are separate checks in the squares project.
- A PASS means the certificate proves its pattern infeasible. What that pattern excludes from the n = 17 census is decided elsewhere.
- The timings above are single runs on shared hosts.

## Data and licence

The code is under the MIT License (see [`LICENSE`](LICENSE)).

Three kinds of data come from the squares project, by Joshua Levy, under CC BY 4.0. None of them is code.

- `tests/cells.json` is the project’s capacity-one cover, exported from its tools.
- `tests/fixtures/small-certificate` was written by the project’s branch-and-bound pilot, including its `README.txt`. The `mutated-*` copies change one field each.
- The exact endpoints in the unit tests were exported from the standing verifier.
