# Regenerating zmx2 with lazy line intersections

A verifier optimization for point certificates. It regenerates the full-domain-compared source
from a fixed patch against Evan Daniel's original implementation. It does not replace the
original source or any published certificate.

## Regeneration

Requires the Python standard library and `patch`; building also requires Rust.

```sh
python performance/point_verifier_lazy/build.py \
  --source <path to upstream s12/verify2/src/bin/zmx2.rs> \
  --out <new directory> \
  --emit-only
```

Without `--emit-only` it builds with Rust 2021, opt-level=3 and LTO. **rustc 1.86 or later is
required** (the upstream source itself uses `f64::next_up/next_down`; with 1.85 the original
fails to build too). `--rustc /path/to/rustc` pins the compiler. The existing comparison was
done with Rust 1.86.0 / x86_64-apple-darwin. A binary produced with another compiler or on
another machine must be re-verified. The binary hash includes the absolute source path, so it
changes with the build location. A 1.86 build on an Apple Silicon machine (Rosetta) was
confirmed to match the census at root 1614. A successful build is not a successful
certification.

The output directory must be new. The SHA-256 of the input source, the patch and the generated
source are pinned; applying to a different version and overwriting existing output are
refused. `receipt.json` records the build conditions and hashes.

## Scope of verification

On the upstream point certificate for n=32, L=6, the original and the improved versions
were run sequentially on Intel with 7 threads, and the certification census of all 3600 roots
matched, with 0 uncertified and 0 capped. 437.450 → 241.004 s (44.907% shorter). This is a
single same-machine comparison and does not guarantee the ratio for mixed certificates or other
machines. The mixed n=45 case initially had only partial regression checks (see below).

The entry point for a full-domain verification is `verify.py` (bound to the receipt; requires a
whole-domain VERIFIED, uncert 0, cap 0, the root count, and a census identical to a reference).
Restricted-region results (REGION CLEAN) or exit code 0 alone must never be taken as a proof.
The mixed certificate for n=45, L=7 was also confirmed to match over the full domain (all
39200 roots, Apple Silicon under Rosetta), but took 468.9 s against 342.7 s previously recorded
for the original (load conditions not identical). No speed-up is claimed for mixed
certificates, so the recommended use is limited to point certificates.

All timings above are reported values from our private runs, not reproduced here. It is not integrated into
any automatic search or publication process.

## Source

Original implementation: Evan Daniel, square-packing commit
`6e1223cf7ef2be4c70baaa36c0e7e7197076735a`, `s12/verify2/src/bin/zmx2.rs`. The patch changes
only the evaluation order in `family_bound` and the handling of zero-density lines.
