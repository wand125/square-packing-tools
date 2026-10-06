"""Rebuild tiny, synthetic whole-tree certificates (no producer dependency)."""
import copy
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'tests/fixtures'
SPAN = ['0/1', '2/1']
BOX = ['1/1', '11/10', '1/1', '11/10']
CELL = [['1/1', '1/1'], ['11/10', '1/1'], ['11/10', '11/10'], ['1/1', '11/10']]
E = [0, *SPAN, 1, 0, [SPAN]]
NODE = dict(id=0, parent=None, angles=[SPAN, SPAN], windows=[], closed='angle',
            rounds=[dict(boxes=[BOX, BOX])], final=[BOX, BOX], angle=[E], split=None)
HEADER = dict(cap='3/1', pattern=['a', 'b'], cells=[CELL, CELL], pairs=[[0, 1]],
              root_angles=[SPAN, SPAN], root_boxes=[BOX, BOX], half_pi_multiples={})

def write(name, nodes, schema='v3', summary=None, trig=None):
    directory = ROOT / name
    directory.mkdir(exist_ok=True)
    for old in directory.glob("*.json.gz"):
        old.unlink()
    def store(value):
        raw = json.dumps(value, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (directory / (digest + '.json.gz')).write_bytes(gzip.compress(raw, mtime=0))
        return digest
    angles = trig or {x: ['-2/1', '2/1', '-2/1', '2/1', '0/1', '0/1'] for x in ['0/1', '1/1', '2/1']}
    manifest = store(dict(schema='n17-subpattern-bb-certificate/' + schema, header=HEADER,
        chunks=[store(dict(nodes=nodes))], trig=store(dict(trig=angles)),
        summary=summary or dict(complete=True, nodes=len(nodes), leaves=1,
                               tighten_nodes=len(nodes)-1, angle_leaves=1)))
    (directory / 'README.txt').write_text('Synthetic v3 regression certificate.\nmanifest: ' + manifest + '\n')

(ROOT / 'v3-cells.json').write_text(json.dumps(dict(U='3/1', order=['a', 'b'], cells=dict(a=CELL, b=CELL))) + '\n')
write('v3-angle', [NODE])
for name, change in [
    ('drop-partner', lambda n: n['angle'][0].__setitem__(5, [])),
    ('wall', lambda n: n.__setitem__('angle', [[0, *SPAN, 'wall']])),
    ('not-empty', lambda n: n.__setitem__('angle', [])),
    ('wrong-pair', lambda n: n['angle'][0].__setitem__(4, 1)),
    ('repeat', lambda n: n['angle'].append(copy.deepcopy(E))),
    ('missing-trig', lambda n: n['angle'][0].__setitem__(1, '1/3')),
    ('small-final', lambda n: n['final'][0].__setitem__(0, '21/20')),
]:
    node = json.loads(json.dumps(NODE))
    change(node)
    write('v3-' + name, [node])
write('v3-in-v1', [NODE], schema='v1')
root = copy.deepcopy(NODE)
root.update(closed=None, angle=None, split={'tighten': [[[0, '0/1', '1/1', 1, 0, [SPAN]]], [['1/1','2/1'], SPAN]]})
child = copy.deepcopy(NODE)
child.update(id=1, parent=0, angles=[['1/1','2/1'], SPAN], angle=[[0,'1/1','2/1',1,0,[SPAN]]])
write('v3-tighten', [root, child])

write('v3-summary', [NODE], summary=dict(complete=True, nodes=1, leaves=1, tighten_nodes=1, angle_leaves=1))
bad = json.loads(json.dumps(root))
bad['split']['tighten'][1][0] = ['2/1','2/1']
bad_child = json.loads(json.dumps(child))
bad_child['angles'][0] = ['2/1','2/1']
write('v3-target', [bad, bad_child])
bad = json.loads(json.dumps(child))
bad['windows'] = [[0, '0/1', '1/1']]
write('v3-child-window', [root, bad])
