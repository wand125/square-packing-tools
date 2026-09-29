import json,shutil,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));import axis_cached as a
HERE=Path(__file__).resolve().parent;SOLVER=HERE.parents[1]/'solver'
class Gate(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.b=Path(self.tmp.name);self.d=self.b/'cert';self.d.mkdir()
  # The gate only checks the runner and verifier hashes and that the input files exist.
  shutil.copy(SOLVER/'run_verify.py',self.d/'run_verify.py')
  (self.d/'certificate_input.txt').write_text('synthetic input\n');(self.d/'certificate_metadata.json').write_text('{}')
  shutil.copy(HERE/'canonical.cpp',self.d/'verify.cpp');shutil.copy(HERE/'axis_cached.cpp',self.b/'axis_cached.cpp');(self.b/'axis-cached.enabled').touch()
  self.argv=[sys.executable,'run_verify.py','--workers','1']
 def run_gate(self):return a.prepare_cached(self.argv,self.d,self.b)
 def test_fresh(self):
  self.assertTrue(self.run_gate());self.assertEqual(a.sha(self.d/'verify.cpp'),a.CACHED_SHA);self.assertEqual(a.sha(self.d/'verify.canonical.cpp'),a.CANONICAL_SHA);self.assertFalse(self.run_gate())
 def test_existing(self):
  (self.d/'verified_angles.jsonl').touch();self.assertFalse(self.run_gate())
 def test_disabled(self):
  (self.b/'axis-cached.enabled').unlink();self.assertFalse(self.run_gate())
 def test_unknown_runner(self):
  (self.d/'run_verify.py').write_text('changed');self.assertFalse(self.run_gate())
 def test_unknown_source(self):
  (self.d/'verify.cpp').write_text('changed');self.assertFalse(self.run_gate())
 def test_tampered_cache(self):
  (self.b/'axis_cached.cpp').write_text('changed')
  with self.assertRaises(RuntimeError):self.run_gate()
 def test_shared_runner(self):
  shutil.copy(self.d/'run_verify.py',self.b/'run_verify.py');self.argv[1]=str(self.b/'run_verify.py');self.assertFalse(self.run_gate())
 def test_canonical_is_solver_verifier(self):
  self.assertEqual(a.sha(SOLVER/'verify.cpp'),a.CANONICAL_SHA);self.assertEqual(a.sha(SOLVER/'run_verify.py'),a.RUNNER_SHA)
if __name__=='__main__':unittest.main()
