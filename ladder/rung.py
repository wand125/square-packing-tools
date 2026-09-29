"""One ladder rung: next rung, bracket or neighbour transfer from a certified parent.

    python ladder/rung.py <case key> <config.json>

The config names the parent certificate (absolute, or relative to the config's directory),
n, L, mode and budget targets; see transfer/make_transfer.py. Results go to
<results root>/<case key>/ (see ladder/paths.py).
"""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[k]='1'
import sys,json,time
from pathlib import Path
from fractions import Fraction as F
from types import SimpleNamespace
import numpy as np
from scipy.stats import qmc
b=Path(__file__).resolve().parent
from paths import use_solver,results_root,resolve_input
code_dir=use_solver(b)
from master import Master
from advance import transfer,load_incumbent
from global_separation_fast import separate_global
from refinement import propose_splits,bisect_long
from certify import certify
from rectangle_rescue import rescue
from residual_recovery import solve_with_recovery
if len(sys.argv)!=3:raise SystemExit('usage: python ladder/rung.py <case key> <config.json>')
case=sys.argv[1];cfg_path=Path(sys.argv[2]).resolve();cfg=json.loads(cfg_path.read_text());n=int(cfg['n'])
mode=cfg['mode'];targetL=float(F(cfg['L']));parents=4;floor=.001
out=results_root(b)/case;out.mkdir(parents=True,exist_ok=False)
(out/'experiment.json').write_text(json.dumps(cfg,indent=2))
t=time.perf_counter();records=[]
def emit(d):
 records.append(d);print(json.dumps(d),flush=True)
 tmp=out/'progress.tmp';tmp.write_text(json.dumps(dict(case=case,seconds=time.perf_counter()-t,records=records),indent=2));tmp.replace(out/'progress.json')
def stop_reason(mass, targets, records, iteration):
    """Classify a no-new-row/no-new-column stop, never a global impossibility."""
    if targets and all(mass >= target for target in targets):
        return 'BUDGET_EXHAUSTED'
    screens = [r for r in records if r.get('operation') == 'screen' and r.get('iteration') == iteration]
    if any(r.get('unknown', 0) > 0 for r in screens):
        return 'SCREEN_INCOMPLETE'
    return 'STALLED_NO_CHANGE'

def configure_solver(m, cfg):
    if cfg.get('residual_ipm_recovery',False) and cfg.get('continue_ipm',False):
        raise ValueError('choose residual recovery or all-IPM, not both')
    solver=cfg.get('initial_solver','simplex')
    if solver not in ('simplex','ipm'):
        raise ValueError('unsupported initial solver')
    if cfg.get('continue_ipm',False) and solver!='ipm':
        raise ValueError('continue_ipm requires initial_solver=ipm')
    m._check(m.h.setOptionValue('solver',solver))
    return dict(operation='solver_policy',initial_solver=solver,continue_ipm=cfg.get('continue_ipm',False),residual_ipm_recovery=cfg.get('residual_ipm_recovery',False))

def after_first_solve(m, cfg, iteration):
    if iteration==0 and cfg.get('initial_solver','simplex')=='ipm' and not cfg.get('continue_ipm',False):
        m._check(m.h.setOptionValue('solver','simplex'))
        return dict(operation='solver_switch',solver='simplex',reason='initial IPM passed original residual gates')
    return None

try:
 parent=load_incumbent(resolve_input(cfg['parent'],cfg_path.parent,b),int(cfg.get('parent_n',n)))
 emit(dict(operation='parent_support',parent_n=int(cfg.get('parent_n',n)),target_n=n,note='Parent proof validates its own budget; transferred support must independently prove target_n.'))
 parent['weights']=[float(F(str(w))) for w in parent['weights']]
 d=transfer(parent,targetL)
 m=Master(targetL,.9977,d['rectangles'],rhs=1.001)
 if cfg.get('keep_inactive'):
  factor=targetL/float(F(str(parent['L'])))
  added=m.add_columns([[float(v)*factor for v in rr] for rr in parent['rectangles']])
  emit(dict(operation='retain_parent_dictionary',added=added))
 if cfg.get('initial_bisection'):
  # Enlarge the initial cone once; retain every original rectangle.
  children=[]
  for rectangle in m.rectangles.copy():
   axis=int(np.argmax(rectangle[2:]-rectangle[:2])) if cfg['initial_bisection']=='long' else int(np.argmin(rectangle[2:]-rectangle[:2]))
   if cfg['initial_bisection']=='both':
    for half in bisect_long(rectangle,0)[0]:children.extend(bisect_long(half,1)[0])
   else:children.extend(bisect_long(rectangle,axis)[0])
  emit(dict(operation='initial_bisection',axis=cfg['initial_bisection'],added=m.add_columns(children)))
 poses=qmc.Sobol(3,scramble=True,seed=925381).random_base2(13);poses[:,:2]=2*poses[:,:2]-1
 x=np.linspace(-1,1,33);xx,yy=np.meshgrid(x,x)
 poses=np.vstack([poses,np.c_[xx.ravel(),yy.ravel(),np.zeros(xx.size)],np.c_[xx.ravel(),yy.ravel(),np.ones(xx.size)]])
 m.add_rows(poses)
 emit(configure_solver(m,cfg))
 for iteration in range(30):
  start=time.perf_counter()
  if cfg.get('residual_ipm_recovery',False) and m.h.getOptionValue('solver')[1]=='simplex':
   def recovery_event(event):
    event=dict(event);operation=event.pop('event');emit(dict(operation=operation,iteration=iteration,**event))
   sol=solve_with_recovery(m,recovery_event)
  else:sol=m.solve()
  emit(dict(operation='lp',iteration=iteration,mass=sol.mass,seconds=time.perf_counter()-start,columns=len(m.rectangles),rows=len(m.poses)))
  switched=after_first_solve(m,cfg,iteration)
  if switched:emit(switched)
  candidate=dict(n=n,L=targetL,B=.9977,rhs=1.001,rectangles=m.rectangles.tolist(),weights=sol.weights.tolist(),mass=sol.mass,globally_verified=False)
  path=out/f'candidate-{iteration}.json';path.write_text(json.dumps(candidate))
  allbad=[];clean=False
  for target_text in cfg['targets']:
   target=float(F(target_text))
   if sol.mass>=target:emit(dict(operation='screen',iteration=iteration,target=target,status='OVER_TARGET'));continue
   bad,r=separate_global(m,SimpleNamespace(weights=sol.weights*(target/sol.mass)),budget=cfg.get('screen_boxes',50000),max_rows=int(cfg.get('max_screen_rows',1000000)))
   emit(dict(operation='screen',iteration=iteration,target=target,returned=len(bad),unknown=len(r['unknown_angles']),angles=r['angles_checked'],status=r['status'],seconds=r['seconds']))
   allbad.extend(bad.tolist())
   if r['status']=='SCREENED_ALL_NET_CENTERS' and not clean:
    proof=rescue(path,n,out/f'proof-{iteration}-{target}',code_dir,F(n)-F(target_text),workers=int(cfg.get('proof_workers',1)))
    emit(dict(operation='proof',iteration=iteration,target=target,result=proof));clean=proof['status']=='CERTIFIED'
  if clean:emit(dict(status='CERTIFIED'));break
  split_added=0
  if mode in ('own_short_split','own_long_split'):
   selected,_=propose_splits(m,sol,max_parents=parents,min_aspect=cfg.get('min_aspect',2.),split_axis=('short' if mode=='own_short_split' else 'long'),short_floor=floor)
   added=m.add_columns([r for x in selected for r in x['children']]);split_added=added;emit(dict(operation='split',iteration=iteration,added=added))
  added=m.add_rows(allbad) if allbad else 0
  np.savez_compressed(out/'resume-state.tmp.npz',rectangles=m.rectangles,poses=m.poses);(out/'resume-state.tmp.npz').replace(out/'resume-state.npz')
  (out/'resume.json').write_text(json.dumps(dict(next_iteration=iteration+1,mode=mode)))
  emit(dict(operation='new_rows',iteration=iteration,added=added))
  if not added and not split_added:
   emit(dict(status=stop_reason(sol.mass,[float(F(x)) for x in cfg['targets']],records,iteration)));break
 else:emit(dict(status='ITERATIONS_EXHAUSTED'))
except Exception as e:
 # Record the actual solver/model state on native run errors as well as residual errors.
 # Capture failures never replace the original failure or change acceptance gates.
 capture={}
 if 'm' in locals():
  try:
   from scipy import sparse
   fail=out/'failure';fail.mkdir(exist_ok=True)
   sparse.save_npz(fail/'cached-matrix.npz',m.A)
   np.savez_compressed(fail/'geometry.npz',rectangles=m.rectangles,poses=m.poses,rhs=m.rhs)
   if m.h is not None:
    capture['model_status']=str(m.h.getModelStatus())
    capture['model_write']=str(m.h.writeModel(str(fail/'model.mps')))
    capture['basis_write']=str(m.h.writeBasis(str(fail/'basis.bas')))
   (fail/'capture.json').write_text(json.dumps(capture,indent=2))
  except Exception as capture_error:capture['capture_error']=repr(capture_error)
 emit(dict(status='ERROR',error=repr(e),capture=capture));raise
