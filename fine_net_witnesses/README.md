# fine_net_witnesses: separated counterexamples for repairing a candidate

A build of the fine-net verifier that, instead of stopping at the first counterexample
candidate of a direction, keeps searching and reports up to K of them, at least S apart.
It is a search aid for the repair step of a certificate generator. Certificates are
verified with `fine_net_verifier/` only.

```bash
(cd sqverify_fast_witnesses && cargo build --release --locked)
python3 ../fine_net_verifier/fine_net_check.py CANDIDATE.json --out DIR --repair \
    --bin sqverify_fast_witnesses/target/release/sqverify-fast \
    [--threshold 10005/10000] [--max-witnesses 32] [--witness-separation 0.02]
```

`DIR/counterexamples.json` lists, per refused direction `r` (half-angle tangent
`t = r·step`), the boxes `{x, y, dx, dy}` whose capture is below the threshold, each with
its exact capture at the centre (`exact_coverage`, `exact_below_threshold`). Centres lie in
the verifier's D4-reduced domain [L/2, U_r]²; the measure is D4-invariant, so any of the
eight images is an equally valid pose. `DIR/repair.json` summarises the run.
