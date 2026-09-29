"""Resume a rung from a saved state (rows and columns), with optional basis restore and free pricing.

    python ladder/trial_guarded.py <case key> [cases.json]

cases.json maps case keys to configs (default: cases.json next to this script); paths inside
are absolute or relative to the cases file's directory.
"""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[k]='1'
import sys,json,time
from pathlib import Path
from fractions import Fraction as F
from types import SimpleNamespace
import numpy as np
from scipy.stats import qmc
from scipy import sparse
b=Path(__file__).resolve().parent
from paths import use_solver,results_root,resolve_input
code_dir=use_solver(b)
from master import Master
from advance import transfer,load_incumbent
from global_separation_fast import separate_global
from refinement import propose_splits
from pricing import propose as propose_free
from certify import certify
from rectangle_rescue import rescue
from checkpoint_basis import save_basis,load_basis
from residual_recovery import solve_with_recovery
if len(sys.argv) not in (2,3):raise SystemExit('usage: python ladder/trial_guarded.py <case key> [cases.json]')
case=sys.argv[1];cases_path=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else b/'cases.json'
cfg=json.loads(cases_path.read_text())[case];n=int(cfg['n'])
def given(name):return resolve_input(cfg[name],cases_path.parent,b)
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

try:
 checkpoint=given('checkpoint')
 data=np.load(checkpoint)
 m=Master(targetL,.9977,data['rectangles'],rhs=1.001)
 m.add_rows(data['poses'])
 emit(dict(operation='resume',checkpoint=str(checkpoint),columns=len(m.rectangles),rows=len(m.poses),start_iteration=cfg['start_iteration']))
 if cfg.get('basis_checkpoint'):
  emit(dict(operation='basis_restore',**load_basis(m,given('basis_checkpoint'))))
 if cfg.get('expected_matrix'):
  expected=sparse.load_npz(given('expected_matrix'))
  if expected.shape!=m.A.shape or (expected!=m.A).nnz:raise ValueError('restored matrix differs from failure capture')
  emit(dict(operation='restored_matrix_checked',rows=m.A.shape[0],columns=m.A.shape[1],matrix_equal=True))
 if cfg.get('residual_ipm_recovery',False) and cfg.get('continue_ipm',False):raise ValueError('choose residual recovery or all-IPM, not both')
 initial_solver=cfg.get('initial_solver','simplex')
 if initial_solver not in ('simplex','ipm'):raise ValueError('unsupported initial solver')
 if initial_solver!='simplex':
  m._check(m.h.setOptionValue('solver',initial_solver));emit(dict(operation='initial_solver',solver=initial_solver))
 for iteration in range(cfg['start_iteration'],cfg['start_iteration']+cfg['max_iterations']):
  start=time.perf_counter()
  if cfg.get('residual_ipm_recovery',False) and m.h.getOptionValue('solver')[1]=='simplex':
   def recovery_event(event):
    event=dict(event);operation=event.pop('event');emit(dict(operation=operation,iteration=iteration,**event))
   sol=solve_with_recovery(m,recovery_event)
  else:sol=m.solve()
  emit(dict(operation='lp',iteration=iteration,mass=sol.mass,seconds=time.perf_counter()-start,columns=len(m.rectangles),rows=len(m.poses)))
  if iteration==cfg['start_iteration'] and initial_solver!='simplex' and not cfg.get('continue_ipm',False):
   m._check(m.h.setOptionValue('solver','simplex'));emit(dict(operation='solver_switch',solver='simplex',reason='initial IPM passed original residual gates'))
  candidate=dict(n=n,L=targetL,B=.9977,rhs=1.001,rectangles=m.rectangles.tolist(),weights=sol.weights.tolist(),mass=sol.mass,globally_verified=False)
  path=out/f'candidate-{iteration}.json';path.write_text(json.dumps(candidate))
  allbad=[];clean=False
  for target_text in cfg['targets']:
   target=float(F(target_text))
   if sol.mass>=target:emit(dict(operation='screen',iteration=iteration,target=target,status='OVER_TARGET'));continue
   bad,r=separate_global(m,SimpleNamespace(weights=sol.weights*(target/sol.mass)),budget=cfg['screen_boxes'],max_rows=cfg['max_screen_rows'])
   emit(dict(operation='screen',iteration=iteration,target=target,returned=len(bad),unknown=len(r['unknown_angles']),angles=r['angles_checked'],status=r['status'],seconds=r['seconds']))
   allbad.extend(bad.tolist())
   if r['status']=='SCREENED_ALL_NET_CENTERS' and not clean:
    proof=rescue(path,n,out/f'proof-{iteration}-{target}',code_dir,F(n)-F(target_text),workers=int(cfg.get('proof_workers',1)))
    emit(dict(operation='proof',iteration=iteration,target=target,result=proof));clean=proof['status']=='CERTIFIED'
  if clean:emit(dict(status='CERTIFIED'));break
  free_columns=[];free_report=None
  if cfg.get('enable_pricing',True) and (iteration == cfg['start_iteration'] or iteration % cfg.get('pricing_every',3) == 0):
   free_columns,free_report=propose_free(m,sol,seed=92620+n+iteration,samples_power=cfg.get('pricing_samples_power',7),local_starts=1,max_columns=cfg.get('pricing_max_columns',16),widths=tuple(cfg.get('pricing_widths',[1/64,1/16,1/4,1/2])))
  split_added=0
  if mode in ('own_short_split','own_long_split'):
   selected,_=propose_splits(m,sol,max_parents=parents,min_aspect=cfg.get('min_aspect',2.),split_axis=('short' if mode=='own_short_split' else 'long'),short_floor=floor)
   added=m.add_columns([r for x in selected for r in x['children']]);split_added=added;emit(dict(operation='split',iteration=iteration,added=added))
  if free_report is not None:
   added_free=m.add_columns([c['rectangle'] for c in free_columns]);split_added+=added_free
   emit(dict(operation='free_pricing',iteration=iteration,added=added_free,report=free_report))
  added=m.add_rows(allbad) if allbad else 0
  np.savez_compressed(out/'resume-state.tmp.npz',rectangles=m.rectangles,poses=m.poses);(out/'resume-state.tmp.npz').replace(out/'resume-state.npz')
  (out/'resume.json').write_text(json.dumps(dict(next_iteration=iteration+1,mode=mode)))
  emit(dict(operation='new_rows',iteration=iteration,added=added))
  if not added and not split_added and free_report is None and cfg.get('enable_pricing',True):
   # A skipped pricing cadence is not evidence that no improving column exists.
   forced_columns,forced_report=propose_free(m,sol,seed=92620+n+iteration,samples_power=cfg.get('pricing_samples_power',7),local_starts=1,max_columns=cfg.get('pricing_max_columns',16),widths=tuple(cfg.get('pricing_widths',[1/64,1/16,1/4,1/2])))
   split_added=m.add_columns([c['rectangle'] for c in forced_columns])
   emit(dict(operation='free_pricing',iteration=iteration,added=split_added,report=forced_report,forced_before_stall=True))
   if split_added:
    np.savez_compressed(out/'resume-state.tmp.npz',rectangles=m.rectangles,poses=m.poses);(out/'resume-state.tmp.npz').replace(out/'resume-state.npz')
  try:
   emit(dict(operation='basis_checkpoint',iteration=iteration,**save_basis(m,out/'basis')))
  except Exception as basis_error:
   emit(dict(operation='basis_checkpoint',iteration=iteration,status='SAVE_FAILED',error=repr(basis_error)))
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
