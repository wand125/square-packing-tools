#!/usr/bin/env python3
"""Run a receipt-bound lazy zmx2 over the whole domain and accept only a complete census.

Acceptance: exit 0, a VERIFIED line and no NOT VERIFIED, every ROOT line parsed with
unique (index, pass), uncert 0 and capped 0 on every root, unchanged input hashes, and,
when given, the expected root count and a census identical (ms excluded) to a reference log.
Restricted-region runs (REGION CLEAN) are never accepted here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = re.compile(r'ROOT (\d+) pass (\d+) root (\S+) boxes (\d+) cert (\d+) empty (\d+) '
                  r'uncert (\d+) maxdepth (\d+) capped (\d+) ms (\d+)')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def census(path):
    rows = [s for s in Path(path).read_text().splitlines() if s.startswith('ROOT ')]
    parsed = [ROOT.fullmatch(s) for s in rows]
    if not all(parsed):
        raise SystemExit(f'unparsed ROOT line in {path}')
    if len({(m[1], m[2]) for m in parsed}) != len(parsed):
        raise SystemExit(f'duplicate root index in {path}')
    return parsed, sorted(re.sub(r' ms \d+$', '', s) for s in rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--receipt', type=Path, required=True, help='receipt.json from build.py (BUILD_SUCCEEDED)')
    ap.add_argument('--binary', type=Path, help='defaults to zmx2-lazy next to the receipt')
    ap.add_argument('--cover', type=Path, required=True)
    ap.add_argument('--mode', choices=['d4', 'full'], required=True)
    ap.add_argument('--threads', type=int, default=1)
    ap.add_argument('--pair-points', action='store_true')
    ap.add_argument('--expect-roots', type=int)
    ap.add_argument('--reference', type=Path, help='accepted roots.log to compare census with')
    ap.add_argument('--out', type=Path, required=True, help='new directory')
    a = ap.parse_args()

    receipt = json.loads(a.receipt.read_text())
    if receipt.get('status') != 'BUILD_SUCCEEDED':
        ap.error('receipt is not a successful build')
    binary = (a.binary or a.receipt.with_name('zmx2-lazy')).resolve()
    if sha(binary) != receipt['binary_sha256']:
        ap.error('binary does not match receipt')
    inputs = [binary, a.cover.resolve(), a.receipt.resolve()] + ([a.reference.resolve()] if a.reference else [])
    bindings = {str(p): sha(p) for p in inputs}
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)

    argv = [str(binary), 'cert', str(a.cover.resolve()), '--' + a.mode, '--threads', str(a.threads),
            '--log', str(out / 'roots.log')] + (['--pair-points'] if a.pair_points else [])
    (out / 'launch.json').write_text(json.dumps(dict(argv=argv, input_sha256=bindings), indent=2) + '\n')
    start = time.monotonic()
    with (out / 'run.log').open('x') as log:
        code = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT).returncode
    result = dict(argv=argv, exit_code=code, seconds=time.monotonic() - start, input_sha256=bindings,
                  modified_source_sha256=receipt['modified_sha256'], status='REJECTED')
    try:
        assert code == 0, 'nonzero exit'
        assert bindings == {p: sha(p) for p in bindings}, 'input changed during run'
        text = (out / 'run.log').read_text()
        assert re.search(r'^VERIFIED(-D4)?:', text, re.M) and 'NOT VERIFIED' not in text, 'no whole-cover verdict'
        assert 'REGION CLEAN' not in text, 'restricted region run'
        parsed, sig = census(out / 'roots.log')
        assert all(int(m[7]) == 0 and int(m[9]) == 0 for m in parsed), 'uncertified or capped root'
        if a.expect_roots is not None:
            assert len(parsed) == a.expect_roots, f'{len(parsed)} roots, expected {a.expect_roots}'
        if a.reference:
            assert sig == census(a.reference)[1], 'census differs from reference'
        result.update(status='FULL_DOMAIN_VERIFIED', roots=len(parsed), uncertified=0, capped=0,
                      census_identical_to_reference=bool(a.reference), roots_sha256=sha(out / 'roots.log'))
    except AssertionError as e:
        result['reason'] = str(e)
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'FULL_DOMAIN_VERIFIED' else 1)


if __name__ == '__main__':
    main()
