# fine_net_verifier: independent check of fine-net density certificates

Checks a rectangle-density lower-bound certificate s(n) ≥ L whose angle net is declared in
the candidate (`proof_net: {step, last}`), with sqverify_fast, a clean-room Rust verifier
from jlevy/squares (interval arithmetic with outward rounding; an exact event sweep at
direction 0). See PROVENANCE.md for the one change to it.

## What is checked

The candidate's measure is the D4 average of its listed rectangles (each row's mass spread
over its eight images under the container's symmetries). With core side B and the net
t_j = j·step (t = tan(θ/2)), j = 0..last:

1. the total mass M is the exact sum of the masses and M < n;
2. B·(1 + step) < 1 and the net reaches past tan(π/8);
3. for every j and every centre in [r(a_j), L − r(a_j)]², a_j = max(0, t_j − step/2),
   r(t) = (1 + 2t − t²)/(2(1 + t²)), the closed square of side B at angle θ_j captures
   measure at least 1.

Then n unit squares cannot fit: each would contain a disjoint core of measure ≥ 1.

## Build and run

```bash
sudo apt-get install -y build-essential curl ca-certificates python3     # Ubuntu 24.04
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.98.0
. "$HOME/.cargo/env"
(cd sqverify_fast && cargo build --release --locked)
python3 fine_net_check.py candidate.json --out out
```

`out/receipt.json` (schema `fine-net-check2-receipt/v1`): `verdict` is `PASS` only when
every direction of the net is verified and the tamper control (every mass scaled by 0.985,
then 0.97, 0.95, 0.9 until refused, on 32 directions) is refused with an exact
counterexample; the script then exits 0. It also records `candidate_digest` (SHA-256 of
the sorted-key JSON of n, L, B, rectangles, points, total_mass, proof_net), the file and
input digests, the verifier's source digest, and the time. On a refusal,
`out/counterexamples.json` lists each refused direction's pose and exact capture.

With 4 threads, a check takes from about a minute (n = 18, 416 directions) to about
25 minutes (832 directions, n around 30).
