"""Optional rectangle-only basis hints, bound to an exact reconstructed LP hash."""
from pathlib import Path
import hashlib,json,os
import numpy as np

def fingerprint(m):
 if len(m.atoms):raise ValueError('rectangle-only basis checkpoint')
 a=m.A.tocsr(copy=True);a.sort_indices()
 h=hashlib.sha256()
 h.update(json.dumps(dict(L=m.L,B=m.B,rhs=m.rhs,shape=a.shape,cost='ones',bounds='nonnegative-unbounded'),sort_keys=True).encode())
 for array in [a.indptr.astype('<i8'),a.indices.astype('<i8'),a.data.astype('<f8')]:h.update(np.ascontiguousarray(array).tobytes())
 return h.hexdigest()

def save_basis(m,directory):
 import highspy
 d=Path(directory);d.mkdir(parents=True,exist_ok=True)
 basis=m.h.getBasis()
 if not basis.valid:return dict(status='SKIPPED_INVALID_BASIS')
 model_hash=fingerprint(m);tmp=d/'basis.next.json'
 payload=json.dumps(dict(rows=[int(x) for x in basis.row_status],columns=[int(x) for x in basis.col_status]),separators=(',',':')).encode()
 tmp.write_bytes(payload);os.replace(tmp,d/'basis.json')
 meta=dict(model_sha256=model_hash,basis_sha256=hashlib.sha256(payload).hexdigest(),rows=m.A.shape[0],columns=m.A.shape[1])
 p=d/'manifest.tmp';p.write_text(json.dumps(meta,indent=2));os.replace(p,d/'manifest.json')
 return dict(status='SAVED',**meta)

def load_basis(m,directory):
 import highspy
 d=Path(directory)
 if not (d/'manifest.json').exists():return dict(status='NOT_FOUND')
 meta=json.loads((d/'manifest.json').read_text())
 if meta['model_sha256']!=fingerprint(m):return dict(status='REJECTED_MODEL_MISMATCH')
 if hashlib.sha256((d/'basis.json').read_bytes()).hexdigest()!=meta['basis_sha256']:return dict(status='REJECTED_BASIS_HASH')
 raw=json.loads((d/'basis.json').read_text())
 if len(raw['rows'])!=m.A.shape[0] or len(raw['columns'])!=m.A.shape[1]:return dict(status='REJECTED_DIMENSIONS')
 basis=highspy.HighsBasis()
 basis.row_status=[highspy.HighsBasisStatus(x) for x in raw['rows']]
 basis.col_status=[highspy.HighsBasisStatus(x) for x in raw['columns']]
 basis.valid=True
 if m.h.setBasis(basis)!=highspy.HighsStatus.kOk:raise RuntimeError('basis restore rejected')
 return dict(status='LOADED',rows=m.A.shape[0],columns=m.A.shape[1])
