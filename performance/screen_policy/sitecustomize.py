"""Import hook for the batch16 screen policy and phase metrics.

Active only when this directory is on PYTHONPATH and SP_SCREEN_POLICY=batch16, e.g.
    PYTHONPATH=performance/screen_policy SP_SCREEN_POLICY=batch16 python ladder/rung.py <case> <config.json>
Opt out with SP_SCREEN_POLICY=full (or unset). Metrics go to $SP_PERFORMANCE_DIR
(default ./performance_metrics).
"""
import os
if os.environ.get('SP_SCREEN_POLICY')=='batch16':
    import importlib.abc
    import importlib.machinery
    import sys
    from pathlib import Path
    from batch16 import wrap
    from runtime_metrics import timed
    os.environ.setdefault('SP_PERFORMANCE_DIR', str(Path.cwd()/'performance_metrics'))
    class ScreenLoader:
        def __init__(self,loader):self.loader=loader
        def create_module(self,spec):return self.loader.create_module(spec)
        def exec_module(self,module):
            self.loader.exec_module(module)
            if module.__name__=='global_separation_fast':
                from parallel_screen import install
                module.separate_global=timed('screen',wrap(install(module)))
                print('{"operation":"screen_policy_enabled","policy":"batch16","full_every":8}',flush=True)
            elif module.__name__=='master':
                module.Master.solve=timed('lp',module.Master.solve)
                for name in ('__init__','add_rows','add_columns'):
                    if hasattr(module.Master,name):
                        setattr(module.Master,name,timed('geometry',getattr(module.Master,name)))
            elif module.__name__=='rectangle_rescue':
                module.rescue=timed('proof',module.rescue)
            elif module.__name__=='pricing':
                module.propose=timed('pricing',module.propose)
            elif module.__name__=='edge_pricing':
                module.propose_edges=timed('pricing',module.propose_edges)
    class ScreenFinder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname not in ('global_separation_fast','master','rectangle_rescue','pricing','edge_pricing'):return None
            spec=importlib.machinery.PathFinder.find_spec(fullname,path)
            if spec and spec.loader:spec.loader=ScreenLoader(spec.loader)
            return spec
    sys.meta_path.insert(0,ScreenFinder())
