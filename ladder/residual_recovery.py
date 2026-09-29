"""Experimental: one IPM retry on a simplex residual failure, same exact LP.
No tolerance changes. The caller's original solve() remains the acceptance gate.
Used by ladder/rung.py only when the config sets residual_ipm_recovery.
"""
import hashlib
import json
import time
import numpy as np
from scipy import sparse


def model_signature(m):
    lp=m.h.getLp();a=lp.a_matrix_
    if int(a.format_)==1:
        native=sparse.csc_matrix((a.value_,a.index_,a.start_),shape=(lp.num_row_,lp.num_col_)).tocsr()
    elif int(a.format_)==2:
        native=sparse.csr_matrix((a.value_,a.index_,a.start_),shape=(lp.num_row_,lp.num_col_))
    else:raise ValueError('unsupported native matrix layout')
    native.sort_indices();cached=m.A.tocsr(copy=True);cached.sort_indices()
    if native.shape!=cached.shape or (native!=cached).nnz:
        raise ValueError('native/cached matrix mismatch; no retry')
    h=hashlib.sha256()
    h.update(json.dumps([lp.num_row_,lp.num_col_,lp.offset_,int(lp.sense_),m.L,m.B,m.rhs]).encode())
    for v in (native.indptr,native.indices,native.data,lp.col_cost_,lp.col_lower_,lp.col_upper_,lp.row_lower_,lp.row_upper_,m.rectangles,m.poses):
        v=np.asarray(v);h.update(str(v.shape).encode());h.update(np.ascontiguousarray(v,dtype='<f8').tobytes())
    return h.hexdigest()


def solve_with_recovery(m, emit=lambda event:None):
    if m.h is None:raise ValueError('native HiGHS required')
    status,solver=m.h.getOptionValue('solver');m._check(status)
    if solver!='simplex':raise ValueError('recovery only wraps simplex')
    signature=model_signature(m);started=time.perf_counter()
    try:
        solution=m.solve()
        if model_signature(m)!=signature:raise ValueError('LP mutated during successful solve')
        return solution
    except RuntimeError as error:
        if not str(error).startswith('LP residual check failed:'):raise
        failed_seconds=time.perf_counter()-started
        if model_signature(m)!=signature:raise ValueError('LP mutated during failed solve; no retry') from error
        emit(dict(event='residual_recovery',failed_seconds=failed_seconds,error=str(error),model_sha256=signature))
        try:
            m._check(m.h.clearSolver())  # discard rejected solver state, keep exact LP
            if model_signature(m)!=signature:raise ValueError('LP mutated by clearSolver')
            m._check(m.h.setOptionValue('solver','ipm'))
            solution=m.solve()  # original residual gate, unchanged
            if model_signature(m)!=signature:raise ValueError('LP mutated during retry')
            emit(dict(event='recovery_passed',seconds=time.perf_counter()-started,mass=solution.mass))
            return solution
        finally:
            m._check(m.h.setOptionValue('solver','simplex'))
