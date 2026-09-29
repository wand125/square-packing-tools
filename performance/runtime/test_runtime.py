import hashlib, json, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from scipy.sparse import csr_matrix, vstack
from master import Master
import runtime_metrics, runtime_solver
from runtime_wrapper import install, configure_screen

class RuntimeTests(unittest.TestCase):
    def test_bounded_screen_default_and_explicit_opt_out(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            entry=Path(d)/'rung.py';(Path(d)/'code').mkdir()  # historical run-directory layout
            configure_screen(entry,['n83_fixed_next908'])
            self.assertEqual(os.environ['SP_SCREEN_AUDIT_BATCH'],'16')
            self.assertEqual(Path(os.environ['SP_SCREEN_WITNESS_DIR']),Path(d).resolve()/'results/n83_fixed_next908/witness-archive')
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            entry=Path(d)/'rung.py';cfg=Path(d)/'case.json'
            cfg.write_text(json.dumps(dict(screen_audit_batch=0)))
            configure_screen(entry,['case',str(cfg)])
            self.assertNotIn('SP_SCREEN_AUDIT_BATCH',os.environ)

    def model(self):
        return SimpleNamespace(A=csr_matrix(np.random.default_rng(12).uniform(.1,1,(60,12))),
                               poses=np.zeros((60,3)),atoms=[],rhs=1.001,_check=Master._check)

    def test_real_append_keeps_all_gates(self):
        m=self.model(); first,_=runtime_solver.solve(m,np.ones(60))
        m.A=vstack([m.A,csr_matrix(np.full((1,12),.03))],format='csr');m.poses=np.zeros((61,3))
        result,report=runtime_solver.solve(m,np.r_[first.dual,0.])
        self.assertTrue(report['reused_solver'])
        self.assertGreaterEqual(float((m.A@result.weights).min()),m.rhs-2e-7)
        self.assertLessEqual(float((m.A.T@result.dual).max()),1+2e-5)

    def fake(self, seconds=1., warm=False):
        return SimpleNamespace(seconds=seconds),dict(reused_solver=warm,working_rows=3,rounds=1)

    def test_warm_failure_retries_once_and_never_accepts_second_failure(self):
        m=self.model();m._working_rows_cache={}
        with patch.object(runtime_solver,'core',side_effect=[RuntimeError('residual'),self.fake()]) as core:
            _,report=runtime_solver.solve(m,np.ones(60))
            self.assertEqual([c.kwargs['reuse'] for c in core.call_args_list],[True,False])
            self.assertEqual(report['cold_recovery'],'residual')
            self.assertEqual(report['reuse_cooldown'],3)
        m=self.model();m._working_rows_cache={}
        with patch.object(runtime_solver,'core',side_effect=RuntimeError('bad')) as core:
            with self.assertRaisesRegex(RuntimeError,'bad'):runtime_solver.solve(m,np.ones(60))
            self.assertEqual(core.call_count,2)

    def test_cold_failure_and_invalid_input_not_retried(self):
        for exception in (RuntimeError('bad'),ValueError('input')):
            with patch.object(runtime_solver,'core',side_effect=exception) as core:
                with self.assertRaises(type(exception)):runtime_solver.solve(self.model(),np.ones(60))
                self.assertEqual(core.call_count,1)

    def test_unseeded_failure_reselects_once_and_checks_full_model(self):
        m=self.model();before=m.A.copy();real=runtime_solver.core;calls=[]
        def attempt(master,dual,**options):
            calls.append(np.asarray(dual).copy())
            if len(calls)==1:raise RuntimeError('initial subset failed')
            return real(master,dual,**options)
        with patch.object(runtime_solver,'core',side_effect=attempt):
            sol,report=runtime_solver.solve(m,np.zeros(60))
        self.assertEqual(len(calls),2);np.testing.assert_array_equal(calls[1],np.r_[np.zeros(44),np.ones(16)])
        self.assertEqual(report['cold_recovery_strategy'],'cold_newest_rows')
        self.assertGreaterEqual(float((m.A@sol.weights).min()),m.rhs-2e-7)
        self.assertLessEqual(float((m.A.T@sol.dual).max()),1+2e-5)
        self.assertEqual((before!=m.A).nnz,0)
        with patch.object(runtime_solver,'core',side_effect=RuntimeError('still bad')) as core:
            with self.assertRaisesRegex(RuntimeError,'still bad'):runtime_solver.solve(self.model(),np.zeros(60))
            self.assertEqual(core.call_count,2)

    def test_invalid_unseeded_input_never_retried(self):
        with patch.object(runtime_solver,'core',side_effect=ValueError('invalid input')) as core:
            with self.assertRaises(ValueError):runtime_solver.solve(self.model(),np.zeros(60))
            self.assertEqual(core.call_count,1)

    def test_repeated_slow_reuse_has_bounded_cold_backoff(self):
        m=self.model()
        outputs=[self.fake(),self.fake(3,True),self.fake(3,True)]+[self.fake() for _ in range(4)]
        with patch.object(runtime_solver,'core',side_effect=outputs) as core:
            for _ in outputs:runtime_solver.solve(m,np.ones(60))
            self.assertEqual([c.kwargs['reuse'] for c in core.call_args_list],[True,True,True,False,False,False,True])

    def test_metrics_active_bounded_and_failure(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,SP_PERFORMANCE_DIR=directory),patch.object(runtime_metrics,'_state',dict(pid=os.getpid(),argv=[],phases={},active=None)):
            p=Path(directory)/(str(os.getpid())+'.json')
            for _ in range(40):
                with runtime_metrics.phase('lp'):
                    self.assertEqual(json.loads(p.read_text())['active']['phase'],'lp')
            with self.assertRaisesRegex(RuntimeError,'test'):
                with runtime_metrics.phase('screen'):raise RuntimeError('test')
            d=json.loads(p.read_text());self.assertIsNone(d['active'])
            self.assertEqual(len(d['phases']['lp']['recent_seconds']),32)
            self.assertEqual(d['phases']['screen']['last']['error'],'RuntimeError')
            with patch.object(Path,'write_text',side_effect=OSError('full')):
                with runtime_metrics.phase('lp'):pass

    def test_wrapper_preserves_model_and_atoms_use_original(self):
        class Model:
            def solve(self,*args,**kwargs):return 'original'
        m=Model();m.__dict__.update(self.model().__dict__)
        before=m.A.copy();poses=m.poses.copy()
        install(Model,runtime_solver.solve)
        m.solve();m.solve()
        self.assertEqual((m.A!=before).nnz,0);np.testing.assert_array_equal(m.poses,poses)
        m.atoms=[1];self.assertEqual(m.solve(),'original')

    def test_original_native_recovery_signature_is_preserved(self):
        import runpy
        root=Path(__file__).resolve().parents[2]
        recovery=runpy.run_path(str(root/'ladder/residual_recovery.py'))
        Managed=type('Managed',(Master,),{})
        install(Managed,runtime_solver.solve)
        m=Managed(3.96,.9977,np.array([[0.,0.,3.96,3.96]]))
        m.add_rows(np.array([[0.,0.,0.],[.4,.3,.1]]))
        m._check(m.h.setOptionValue('solver','simplex'))
        before=recovery['model_signature'](m)
        recovery['solve_with_recovery'](m)
        self.assertEqual(recovery['model_signature'](m),before)

    def test_failed_adapter_retains_original_solver_path(self):
        class Model:
            atoms=[]
            poses=np.zeros((1,3))
            def solve(self):return 'original'
        managed=__import__('unittest.mock',fromlist=['Mock']).Mock(side_effect=RuntimeError('bad'))
        install(Model,managed);m=Model()
        self.assertEqual(m.solve(),'original');self.assertEqual(m.solve(),'original')
        self.assertEqual(managed.call_count,1)

if __name__=='__main__':unittest.main()
