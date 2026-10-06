# Provenance of `fine_net_witnesses/`

`sqverify_fast_witnesses/` is `fine_net_verifier/sqverify_fast` (jlevy/squares
`packing/sqverify_fast` with the `proof_net` change) plus a search aid for repairing
candidates. It is not used to verify certificates.

| | commit |
|---|---|
| upstream base (jlevy/squares `main`) | `dee22b882499a295b05424ca5a25121195259ebf` |
| `fine_net_verifier/` (branch `wand125/sqverify-proof-net`) | `fe12e036c822324c12e11915fb83e4ac524acc5a` |
| this directory (branch `wand125/sqverify-witnesses`) | `62826eea8b8984d8ad9a0a9f3c32e2bc7ad88e0e` |

`patches/witnesses.diff` is the change over `fine_net_verifier/`; `patches/from_upstream.diff`
the whole change over the upstream base.

| file | status |
|---|---|
| `src/rotated.rs` | modified: with `max_witnesses > 1`, a counterexample candidate does not stop the search; the box is dropped and the search goes on, keeping candidates whose centres are at least `witness_separation` apart |
| `src/lib.rs` | modified: the collected candidates in the receipt, each with its exact capture under `--confirm` |
| `src/main.rs` | modified: `--max-witnesses K`, `--witness-separation S` |
| `tests/adversarial.rs` | modified: the new `Limits` fields (default 1, the verifier's behaviour) |
| the `proof_net` change | as in `fine_net_verifier/PROVENANCE.md` |
| every other file | upstream, unchanged |

Licences as in `fine_net_verifier/`: code MIT, documentation CC BY 4.0.
