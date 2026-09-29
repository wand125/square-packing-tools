"""Angle-parallel rectangle screen: identical results, several threads.

`separate_global` checks 200 net angles one after another in a single thread.
The angles are independent, so this runs them on a thread pool with a nogil
compilation of the same `verify_angle` and consumes the results strictly in the
original order.  Every break, witness, node count and status is decided in the
same sequence as the sequential loop; angles computed past the stopping point
are discarded.  Only wall-clock time changes.

Enabled by SP_PARALLEL_SCREEN_THREADS=<threads> (e.g. 8), and loaded through the
screen_policy import hook (sitecustomize.py, SP_SCREEN_POLICY=batch16).
SP_PARALLEL_SCREEN=0 disables it per process.  Unknown `separate_global` sources
are left untouched.
"""
import concurrent.futures
import hashlib
import inspect
import json
import os
import threading
from time import perf_counter

import numpy as np

# sha256 of inspect.getsource(separate_global) for the audited implementation.
KNOWN = {'48846bab729d4148f592f5669f73ac1d9c6df2d5874d657f2c3d8a17dfc3b393'}
_executor = None
_executor_lock = threading.Lock()
_compiled = {}


def source_digest(function):
    return hashlib.sha256(inspect.getsource(function).encode()).hexdigest()


def settings():
    if os.environ.get('SP_PARALLEL_SCREEN') == '0' or not os.environ.get('SP_PARALLEL_SCREEN_THREADS'):
        return None
    return dict(threads=max(1, int(os.environ['SP_PARALLEL_SCREEN_THREADS'])))


def nogil_kernel(kernel):
    py = getattr(kernel, 'py_func', None)
    if py is None: return None
    if py not in _compiled:
        from numba import njit
        _compiled[py] = njit(nogil=True)(py)
    return _compiled[py]


def pool():
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix='screen')
        return _executor


def install(module):
    original = module.separate_global
    if getattr(original, '_parallel_screen', False): return original
    try: digest = source_digest(original)
    except (OSError, TypeError): digest = None
    if digest not in KNOWN:
        print(json.dumps(dict(operation='parallel_screen_skipped', reason='unknown separate_global source', sha256=digest)), flush=True)
        return original
    Geometry = module.Geometry; axis_values = module.axis_values

    def separate_global(master, solution, target=1.0005, budget=1000000, max_rows=24, preferred_angles=()):
        cfg = settings()
        kernel = nogil_kernel(module.verify_angle) if cfg else None
        if kernel is None:
            return original(master, solution, target, budget, max_rows, preferred_angles)
        # Below is original separate_global verbatim, except the angle loop.
        if not 1.0001<target<master.rhs-1e-6 or budget<1 or max_rows<1:raise ValueError('invalid search settings')
        if len(getattr(master,'atoms',[])):raise ValueError('rectangle-only experimental oracle')
        start=perf_counter();weights=np.asarray(solution.weights)
        if hasattr(master,'rect_cols'):weights=weights[master.rect_cols]
        active=weights>0;weights=weights[active]
        model=Geometry(master.L,master.B,np.asarray(master.rectangles)[active])
        p,values=axis_values(model,weights);axis_seconds=perf_counter()-start
        poses=[]
        for i in np.argsort(values):
            if values[i]>=target*(1+1e-7) or len(poses)>=max_rows:break
            poses.append([p[i%len(p)],p[i//len(p)],0.])
        order=[]
        for angle in preferred_angles:
            if int(angle)!=angle or not 1<=angle<=200:raise ValueError('invalid preferred angle')
            if angle not in order:order.append(int(angle))
        order.extend(a for a in range(1,201) if a not in order)
        rho=np.repeat(weights/8,8)/model.areas/target;cases=[];unknown=[];nodes=0
        threads, release = cfg['threads'], (lambda: None)
        full = model.full; B = master.B; L = master.L

        def run(angle):
            t=83*angle/40000;c,s=(1-t*t)/(1+t*t),2*t/(1+t*t)
            return c,s,t,kernel(c,s,B,L,full,rho,budget)

        executor = pool(); futures = {}; nxt = 0; discarded = 0
        try:
            for index, angle in enumerate(order):
                if len(poses)>=max_rows:break
                while nxt < len(order) and nxt < index+threads:
                    futures[nxt] = executor.submit(run, order[nxt]); nxt += 1
                c,s,t,(status,visited,leaves,minimum,witness,pending,lower) = futures.pop(index).result()
                nodes+=visited;cases.append({'r':angle,'status':int(status),'nodes':int(visited)})
                if status==0:
                    e=(master.L-master.B*(c+s))/2;u,v=(witness[:2]-master.L/2)/e;a=2*np.arctan(t)/(np.pi/4)
                    if a>1:u,v,a=v,u,2-a
                    poses.append(np.clip([u,v,a],[0,0,0],[1,1,1]))
                elif status==-1:unknown.append(angle)
        finally:
            leftover = [f for f in futures.values() if not f.cancel()]
            discarded = len(futures)
            if leftover:
                threading.Thread(target=lambda: (concurrent.futures.wait(leftover), release()), daemon=True).start()
            else: release()
        complete=len(cases)==200 and not unknown and not poses
        poses=np.asarray(poses).reshape(-1,3)
        checked=model.matrix(poses)@weights if len(poses) else np.array([])
        poses=poses[checked<master.rhs-2e-7]
        return poses,{'operation':'global_separation','status':'SCREENED_ALL_NET_CENTERS' if complete else ('COUNTEREXAMPLES' if len(poses) else 'UNRESOLVED'),
          'angles_checked':len(cases)+1,'unknown_angles':unknown,'axis_minimum':float(values.min()),'axis_poses':len(values),
          'axis_seconds':axis_seconds,'new_rows':len(poses),'nodes':int(nodes),'seconds':perf_counter()-start,
          'screening_target':target,'globally_verified':False,'angles':cases,
          'parallel_screen':{'threads':threads,'discarded_angles':discarded}}

    separate_global.__wrapped__ = original
    separate_global.__signature__ = inspect.signature(original)
    separate_global._parallel_screen = True
    return separate_global
