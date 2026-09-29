"""Opt-in cached axis verification for fresh certificate directories only."""
import hashlib
import json
import os
from pathlib import Path

CANONICAL_SHA = 'a75140df1b484ad104a214d2e8de87afda9fca5929341ec40121afde0c1af602'
CACHED_SHA = 'd796c3209dbf622c44d82573b561da968ca0c8113b12e2119bab05695d7f824b'
RUNNER_SHA = '7bce246763cac8a2bda9aa4cfd9944aa5e14cde9ac965e00686c25f21ae78261'
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def prepare_cached(argv, cwd, base):
    cwd, base = Path(cwd).resolve(), Path(base).resolve()
    if not (base/'axis-cached.enabled').exists(): return False
    if len(argv)!=4 or argv[2]!='--workers': return False
    runner=Path(argv[1]);runner=runner if runner.is_absolute() else cwd/runner
    source=cwd/'verify.cpp'
    if runner.resolve().parent!=cwd or runner.name!='run_verify.py': return False
    if not runner.is_file() or sha(runner)!=RUNNER_SHA: return False
    if not source.is_file() or source.is_symlink() or sha(source)!=CANONICAL_SHA: return False
    if any((cwd/n).exists() for n in ('verification_summary.json','verified_angles.jsonl','verify.canonical.cpp','axis_cache_provenance.json')): return False
    cached=base/'axis_cached.cpp'
    if sha(cached)!=CACHED_SHA: raise RuntimeError('cached verifier hash mismatch')
    # Only the fresh certificate copy is changed, never a shared code directory.
    if not (cwd/'certificate_input.txt').is_file() or not (cwd/'certificate_metadata.json').is_file(): return False
    (cwd/'verify.canonical.cpp').write_bytes(source.read_bytes())
    provenance=dict(canonical_sha256=CANONICAL_SHA,cached_sha256=CACHED_SHA,
                    input_sha256=sha(cwd/'certificate_input.txt'),publication_requires_canonical_replay=True)
    (cwd/'axis_cache_provenance.json').write_text(json.dumps(provenance,indent=2))
    tmp=cwd/f'.verify.cpp.{os.getpid()}.tmp';tmp.write_bytes(cached.read_bytes());tmp.replace(source)
    return True
