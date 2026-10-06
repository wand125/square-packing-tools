# Provenance of `fine_net_verifier/`

`sqverify_fast/` is the measure-capture verifier `packing/sqverify_fast` of
[jlevy/squares](https://github.com/jlevy/squares), a clean-room Rust verifier of
rectangle-density lower-bound certificates, with one change.

| | commit |
|---|---|
| upstream base (jlevy/squares `main`) | `dee22b882499a295b05424ca5a25121195259ebf` |
| this directory (branch `wand125/sqverify-proof-net`) | `fe12e036c822324c12e11915fb83e4ac524acc5a` |

The change (`patches/proof_net.diff`, `git diff` of `packing/sqverify_fast` between the two
commits):

| file | status |
|---|---|
| `src/certificate.rs` | modified: a format M candidate may declare its uniform angle net as `proof_net: {step, last}`; admission then takes the step and the direction count `last + 1` from it and checks the same net premises as for the default net (B(1 + D) < 1, the per-bin tangent form, the endpoint past pi/4, last·step ≤ 1/2). Certificate metadata still never changes a net. |
| `tests/adversarial.rs` | modified: admission of a 1/1001 net with its per-bin domain; refusal of each broken net premise and of malformed declarations |
| `SOUNDNESS.md`, `README.md` | modified: the declared net and its tests |
| every other file | upstream, unchanged |

`fine_net_check.py` is ours: it runs the verifier on every direction of a candidate's
declared net, runs a tamper control, and writes one receipt (see README.md).

Licences: the code in `sqverify_fast/` is MIT; its documentation (`README.md`,
`SOUNDNESS.md`, `INDEPENDENCE.md`, `independence-record.yaml`) is CC BY 4.0. See
THIRD_PARTY_NOTICES.md at the repository root.
