"""Run external v3 certificates and tampering checks; retain receipts and peak RSS.

Run after cargo build --release. Inputs are read only; all output stays in this repo.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, default=ROOT.parent / 'joint_tools')
parser.add_argument('--threads', type=int, nargs='+', default=[1, 4])
parser.add_argument('--skip-tamper', action='store_true')
args = parser.parse_args()
OUT = ROOT / 'results/tighten'
OUT.mkdir(exist_ok=True)
IGNORE = {'seconds', 'directory', 'provenance', 'cells_source', 'sample'}

def run(directory, manifest, tag, threads):
    command = [str(ROOT / 'target/release/n17bb-verify'), str(directory),
               '--manifest', manifest, '--threads', str(threads)]
    # A fresh helper process gives per-run RUSAGE_CHILDREN (no cumulative RSS).
    command = [sys.executable, str(ROOT / 'scripts/measure.py'), *command]
    result = subprocess.run(command, capture_output=True, text=True)
    receipt = json.loads(result.stdout)
    receipt.pop('directory', None)
    (OUT / (tag + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    (OUT / (tag + '.time.txt')).write_text(result.stderr)
    rss = json.loads(result.stderr)['peak_rss_bytes']
    print(tag, receipt['status'], receipt['seconds'], 's', round(rss / 2**20, 2), 'MiB', flush=True)
    return result.returncode, receipt, rss

measurements = []
for name in ['A', 'C1', 'C2']:
    base = args.data / 'runs/cert3'
    manifest = json.loads((base / (name + '.json')).read_text())['certificate_manifest']
    expected = json.loads((base / (name + '_verify.json')).read_text())
    for threads in args.threads:
        code, got, rss = run(base / name, manifest, f'{name}-t{threads}', threads)
        assert code == 0, got
        left = {k: v for k, v in got.items() if k not in IGNORE}
        right = {k: v for k, v in expected.items() if k not in IGNORE}
        assert left == right, {k: (left.get(k), right.get(k)) for k in left.keys() | right.keys() if left.get(k) != right.get(k)}
        measurements.append(dict(certificate=name, threads=threads, seconds=got['seconds'], peak_rss_bytes=rss, receipt_agreement=True))
    (OUT / 'measurements.json').write_text(json.dumps(measurements, indent=2) + '\n')
if not args.skip_tamper:
    for name, message in {
        'drop_partner_interval': 'partner intervals do not cover alive set',
        'pair_as_wall': 'wall elimination not proved',
        'widen_eliminated': 'pair elimination not always overlapping',
        'angle_not_empty': 'angle closure has no empty alive set',
        'wrong_pair_index': 'invalid elimination pair',
        'drop_window': 'angle split children mismatch',
    }.items():
        directory = args.data / 'tamper/out' / name
        manifest = (directory / 'TAMPER.txt').read_text().splitlines()[1].split()[-1]
        code, got, _ = run(directory, manifest, 'tamper-' + name, args.threads[-1])
        assert code == 1 and any(message in f for f in got['failures']), got
        if name == 'drop_window':
            assert any('P2: pieces do not cover' in f for f in got['failures']), got
print('All requested receipt and tamper checks agree.', flush=True)
