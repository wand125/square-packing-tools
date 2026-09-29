"""Bound LP row admission while retaining every audit witness on disk.

A nonempty deferred batch is always COUNTEREXAMPLES, never clearance. Once
all deferred poses are satisfied, a fresh oracle call is mandatory.
"""
from pathlib import Path
import os,json,time
import numpy as np


def coverage(master, solution, poses):
    from geometry import Geometry
    weights=np.asarray(solution.weights)
    if hasattr(master,'rect_cols'):weights=weights[master.rect_cols]
    active=weights>0
    model=Geometry(master.L,master.B,np.asarray(master.rectangles)[active])
    return np.concatenate([model.matrix(poses[i:i+256])@weights[active] for i in range(0,len(poses),256)])


def take(master, solution, limit):
    state=getattr(master,'_screen_witness_batches',None)
    if not state or not len(state['pending']):return None
    start=time.perf_counter();poses=state['pending'];values=coverage(master,solution,poses)
    if not np.isfinite(values).all():raise ValueError('nonfinite deferred witness coverage')
    bad=np.flatnonzero(values<master.rhs-2e-7)
    ordered=bad[np.argsort(values[bad],kind='stable')];selected=ordered[:limit]
    state['pending']=poses[ordered[limit:]]
    if not len(selected):return None
    return poses[selected],dict(operation='global_separation',status='COUNTEREXAMPLES',angles_checked=0,unknown_angles=[],new_rows=len(selected),nodes=0,seconds=time.perf_counter()-start,globally_verified=False,deferred_witnesses=len(state['pending']),witness_archive=state['archive'],source='saved_audit_witnesses')


def admit(master, bad, report, limit):
    if len(bad)<=limit:return bad,report
    root=Path(os.environ.get('SP_SCREEN_WITNESS_DIR') or os.environ.get('SP_RESIDUAL_DUMP_DIR') or (Path(__file__).resolve().parent/'witness-archive'))
    root.mkdir(parents=True,exist_ok=True)
    name=f'screen-{os.getpid()}-{time.time_ns()}.npz';path=root/name
    # Exclusive, durable snapshot must succeed before withholding any witness.
    with path.open('xb') as f:
        np.savez_compressed(f,poses=np.asarray(bad),report=json.dumps(report));f.flush();os.fsync(f.fileno())
    state=getattr(master,'_screen_witness_batches',None)
    pending=np.asarray(bad[limit:]).copy()
    if state and len(state['pending']):pending=np.vstack([state['pending'],pending])
    master._screen_witness_batches=dict(pending=pending,archive=str(path))
    report=dict(report,new_rows=limit,audit_witnesses=len(bad),deferred_witnesses=len(pending),witness_archive=str(path))
    return bad[:limit],report
