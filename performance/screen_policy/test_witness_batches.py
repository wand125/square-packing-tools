import unittest,tempfile,os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import witness_batches as w
class Witnesses(unittest.TestCase):
 def test_real_geometry_rechecks_after_weights_change(self):
  from geometry import Geometry
  m=SimpleNamespace(L=4.,B=.9977,rhs=1.001,rectangles=np.array([[0.,0.,1.,1.]]))
  poses=np.array([[0.,0.,0.],[.2,.1,.2],[.3,-.2,.4]])
  sol=SimpleNamespace(weights=np.array([10.]))
  expected=Geometry(m.L,m.B,m.rectangles).matrix(poses)@sol.weights
  np.testing.assert_allclose(w.coverage(m,sol,poses),expected)
  m._screen_witness_batches=dict(pending=poses,archive='saved')
  sol.weights[:]=0.
  bad,r=w.take(m,sol,2)
  self.assertEqual(len(bad),2);self.assertFalse(r['globally_verified'])
 def test_restart_does_not_claim_clearance_from_archive(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,SP_SCREEN_WITNESS_DIR=d):
   m=SimpleNamespace(rhs=1.001);w.admit(m,np.zeros((20,3)),dict(status='COUNTEREXAMPLES'),16)
   restarted=SimpleNamespace(rhs=1.001)
   self.assertIsNone(w.take(restarted,None,16)) # caller must execute fresh oracle
   self.assertEqual(len(list(Path(d).glob('*.npz'))),1)
 def test_all_saved_bounded_and_rechecked(self):
  m=SimpleNamespace(rhs=1.001);poses=np.arange(180).reshape(60,3)/180
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,SP_SCREEN_WITNESS_DIR=d):
   bad,r=w.admit(m,poses,dict(status='COUNTEREXAMPLES',angles_checked=201),16)
   self.assertEqual(len(bad),16);self.assertEqual(len(m._screen_witness_batches['pending']),44)
   with np.load(r['witness_archive']) as z:np.testing.assert_array_equal(z['poses'],poses)
   with patch.object(w,'coverage',return_value=np.zeros(44)):
    bad,r=w.take(m,None,16);self.assertEqual(len(bad),16);self.assertEqual(r['angles_checked'],0);self.assertEqual(r['status'],'COUNTEREXAMPLES')
   with patch.object(w,'coverage',return_value=np.full(28,1.002)):
    self.assertIsNone(w.take(m,None,16));self.assertEqual(len(m._screen_witness_batches['pending']),0)
 def test_failed_archive_does_not_hide_witnesses(self):
  m=SimpleNamespace(rhs=1.001)
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'file';f.touch()
   with patch.dict(os.environ,SP_SCREEN_WITNESS_DIR=str(f)):
    with self.assertRaises(FileExistsError):w.admit(m,np.zeros((17,3)),{},16)
  self.assertFalse(hasattr(m,'_screen_witness_batches'))
 def test_nonfinite_rejected(self):
  m=SimpleNamespace(rhs=1.001,_screen_witness_batches=dict(pending=np.zeros((1,3)),archive='x'))
  with patch.object(w,'coverage',return_value=np.array([np.nan])):
   with self.assertRaises(ValueError):w.take(m,None,16)
if __name__=='__main__':unittest.main()
