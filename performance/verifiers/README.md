# Axis-direction cache for rectangle proofs

`canonical.cpp` is the standard verifier used for publication (SHA-256 a75140df…; identical to
`solver/verify.cpp`). `axis_cached.cpp` is a search-time verifier that caches only the widths
for r=0. At every point it keeps the order `(rho * lx) * ly` and the order in which rectangles
are summed. The y-direction cache is split into chunks of about 256 MiB, plus one x column and
the vector bookkeeping. For huge inputs where a single row exceeds 256 MiB, chunks are one row.

`axis_cached.py` (`prepare_cached(argv, cwd, base)`) is active only when
`<base>/axis-cached.enabled` exists; `<base>` must also contain `axis_cached.cpp`. It accepts
only the runner and standard verifier with known hashes (`solver/run_verify.py`,
`solver/verify.cpp`), and only changes a fresh certificate directory with no verification log
yet. Shared code and existing certificate directories are never changed. A copy of the
standard verifier (`verify.canonical.cpp`) and a provenance file are left in the certificate
directory. Call it with the verifier command line (`[python, 'run_verify.py', '--workers', N]`)
and the certificate directory before running that command; delete `<base>/axis-cached.enabled`
to disable it. Verifications already started are not affected.

A certificate verified with the cached verifier must be re-verified over all 201 angles with the
standard `verify.cpp` before publication. The hash of the known fast verifier is pinned in
`axis_cached.py`; if either source changes, redo the equality checks.

Tests: `python -m pytest performance/verifiers`
