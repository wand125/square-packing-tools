import unittest,math,tempfile,subprocess,os,sys,json
from pathlib import Path
from types import SimpleNamespace
from batch16 import wrap
class Schedule(unittest.TestCase):
 def make(self,responses=None):
  calls=[];responses=list(responses or [])
  def original(master,solution,target=1.0005,budget=1000000,max_rows=24,preferred_angles=()):
   calls.append(dict(target=target,budget=budget,max_rows=max_rows,preferred=list(preferred_angles)))
   if responses:return responses.pop(0)
   return [[0,0,2*math.atan(83*17/40000)/(math.pi/4)]],dict(status='COUNTEREXAMPLES',angles_checked=2,unknown_angles=[],seconds=1,nodes=5)
  return wrap(original),calls,SimpleNamespace(poses=[])
 def test_schedule_and_model_isolation(self):
  f,c,m=self.make()
  for i in range(16):f(m,None,budget=123,max_rows=1000000)
  self.assertEqual([i+1 for i,x in enumerate(c) if x['max_rows']==1000000],[8,16]);self.assertTrue(all(x['budget']==123 and x['target']==1.0005 for x in c));self.assertEqual(c[1]['preferred'],[17]);self.assertEqual(c[7]['preferred'],[])
  f(SimpleNamespace(poses=[]),None);self.assertEqual(c[-1]['max_rows'],16)
 def test_empty_partial_is_retried_full(self):
  empty=([],dict(status='UNRESOLVED',angles_checked=9,unknown_angles=[],seconds=2,nodes=10))
  clear=([],dict(status='SCREENED_ALL_NET_CENTERS',angles_checked=201,unknown_angles=[],seconds=7,nodes=20))
  f,c,m=self.make([empty,clear]);bad,r=f(m,None);self.assertEqual([x['max_rows'] for x in c],[16,1000000]);self.assertEqual(r['seconds'],9);self.assertEqual(r['nodes'],30);self.assertTrue(r['screen_policy']['empty_result_full_fallback'])
 def test_invalid_clear_rejected(self):
  f,c,m=self.make([([],dict(status='SCREENED_ALL_NET_CENTERS',angles_checked=201,unknown_angles=[4],seconds=1,nodes=1))]*2)
  with self.assertRaises(RuntimeError):f(m,None)
 def test_unknown_preserved(self):
  row=([[0,0,0]],dict(status='COUNTEREXAMPLES',angles_checked=201,unknown_angles=[7],seconds=1,nodes=2));f,c,m=self.make([row]);bad,r=f(m,None);self.assertEqual(r['unknown_angles'],[7]);self.assertEqual(bad,[[0,0,0]])
 def test_smaller_explicit_limit_and_positional_args(self):
  f,c,m=self.make();f(m,None,1.0006,99,8,());self.assertEqual(c[0]['max_rows'],8);self.assertEqual(c[0]['target'],1.0006)
 def test_complete_clear_no_duplicate_scan(self):
  f,c,m=self.make([([],dict(status='SCREENED_ALL_NET_CENTERS',angles_checked=201,unknown_angles=[],seconds=2,nodes=10))]);f(m,None);self.assertEqual(len(c),1)
 def test_idempotent(self):
  f,_,_=self.make();self.assertIs(wrap(f),f)
 def test_deferred_batches_cannot_report_clearance(self):
  import numpy as np
  from unittest.mock import patch
  rows=np.zeros((48,3))
  full=(rows,dict(status='COUNTEREXAMPLES',angles_checked=201,unknown_angles=[],seconds=2,nodes=10))
  clear=([],dict(status='SCREENED_ALL_NET_CENTERS',angles_checked=201,unknown_angles=[],seconds=1,nodes=5))
  f,c,m=self.make([full,clear]);m.rhs=1.001
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,SP_SCREEN_AUDIT_BATCH='16',SP_SCREEN_WITNESS_DIR=d):
   bad,r=f(m,None);self.assertEqual(len(bad),16);self.assertEqual(r['audit_witnesses'],48)
   with patch('witness_batches.coverage',return_value=np.zeros(32)):
    bad,r=f(m,None);self.assertEqual(len(bad),16);self.assertEqual(r['status'],'COUNTEREXAMPLES');self.assertEqual(len(c),1)
   with patch('witness_batches.coverage',return_value=np.full(16,1.002)):
    bad,r=f(m,None);self.assertEqual(len(bad),0);self.assertEqual(r['status'],'SCREENED_ALL_NET_CENTERS');self.assertEqual(len(c),2)
 def test_import_hook_and_opt_out(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'global_separation_fast.py').write_text('def separate_global(master,solution,target=1.0005,budget=1000000,max_rows=24,preferred_angles=()): return None\n')
   env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).parent)+os.pathsep+d
   for policy,want in [('batch16','True'),('full','False')]:
    env['SP_SCREEN_POLICY']=policy;p=subprocess.run([sys.executable,'-c','import global_separation_fast as g; print(bool(getattr(g.separate_global,"_batch16_wrapped",False)))'],cwd=d,env=env,text=True,capture_output=True);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.splitlines()[-1],want)
 def test_phase_hook_records_geometry_and_lp_without_changing_results(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'master.py').write_text('class Master:\n def __init__(self):pass\n def add_rows(self):return 3\n def solve(self):return 7\n')
   env=dict(os.environ,PYTHONPATH=str(Path(__file__).parent)+os.pathsep+d,SP_SCREEN_POLICY='batch16',SP_PERFORMANCE_DIR=str(Path(d,'metrics')))
   p=subprocess.run([sys.executable,'-c','from master import Master; m=Master(); assert m.add_rows()==3; assert m.solve()==7'],cwd=d,env=env,text=True,capture_output=True)
   self.assertEqual(p.returncode,0,p.stderr)
   evidence=json.loads(next(Path(d,'metrics').glob('*.json')).read_text())
   self.assertEqual(evidence['phases']['geometry']['count'],2);self.assertEqual(evidence['phases']['lp']['count'],1)
if __name__=='__main__':unittest.main()
