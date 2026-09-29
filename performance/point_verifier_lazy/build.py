#!/usr/bin/env python3
"""Reproduce the pinned research optimization without modifying upstream files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ORIGINAL = '6b7f0f79466bf25c9a85f8fe2f3866de734935f0521ea188136818c2fb5b3fed'
MODIFIED = 'df83599ef128b8c5ccd328a226d682fd18ddbab4b6bb28ae9c515ac938f39c2e'
PATCH = 'f2f306a47bc1a38cb3f2f22e4915ea3d815348c516c82b582d222250bf78f076'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True, help='Pinned upstream zmx2.rs')
    ap.add_argument('--out', type=Path, required=True, help='New directory; existing paths rejected')
    ap.add_argument('--rustc', default='rustc')
    ap.add_argument('--emit-only', action='store_true', help='Reproduce and check source, without compiling')
    args = ap.parse_args()
    original = args.source.read_bytes()
    patch = Path(__file__).with_name('lazy-endpoints.patch').resolve()
    if digest(original) != ORIGINAL:
        ap.error('upstream source hash mismatch; refusing to apply optimization')
    if digest(patch.read_bytes()) != PATCH:
        ap.error('patch hash mismatch')
    out = args.out.resolve()
    if out.exists():
        ap.error('output already exists; choose a new directory')
    patch_exe = shutil.which('patch')
    if not patch_exe:
        ap.error('patch executable not found')
    rustc = None
    if not args.emit_only:
        rustc = shutil.which(args.rustc)
        if not rustc:
            ap.error('rustc not found; use --rustc or --emit-only')
    out.mkdir(parents=True, exist_ok=False)
    src = out / 'zmx2.rs'
    src.write_bytes(original)
    applied = subprocess.run([patch_exe, '--batch', '--fuzz=0', '-p1', '-i', str(patch)],
                             cwd=out, capture_output=True, text=True)
    (out / 'patch.log').write_text(applied.stdout + applied.stderr)
    applied.check_returncode()
    if digest(src.read_bytes()) != MODIFIED:
        raise RuntimeError('generated source differs from full-domain-tested source')
    receipt = dict(status='PINNED_SOURCE_REPRODUCED', original_sha256=ORIGINAL,
                   modified_sha256=MODIFIED, patch_sha256=PATCH,
                   builder_sha256=digest(Path(__file__).read_bytes()),
                   numerical_replay_performed=False, production_deployed=False)
    if rustc:
        receipt['rustc_version'] = subprocess.check_output([rustc, '-Vv'], text=True)
        command = [rustc, '--edition=2021', '-C', 'opt-level=3', '-C', 'lto=true',
                   str(src), '-o', str(out / 'zmx2-lazy')]
        receipt['build_command'] = command
        with (out / 'build.log').open('x') as log:
            built = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        receipt['build_exit_code'] = built.returncode
        receipt['status'] = 'BUILD_SUCCEEDED' if built.returncode == 0 else 'BUILD_FAILED'
        if built.returncode == 0:
            receipt['binary_sha256'] = digest((out / 'zmx2-lazy').read_bytes())
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        built.check_returncode()
    else:
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
