"""Budget-recovery ladder rung (pricing_rounds read from the config).

    python ladder/edge_rung.py <key> [<config.json>]

Starts from a certified rung's saved rows and columns at a larger L, prices first with 4-edge moves, then
screens, repairs and proves as before. The config defaults to <key>.json next to this script; its
`checkpoint` is absolute or relative to the config's directory (see transfer/make_edge.py).
Monitored via <results root>/<key>/progress.json (see ladder/paths.py)."""
import json, os, runpy, sys
from pathlib import Path
b=Path(__file__).resolve().parent; sys.path.insert(0,str(b))
from paths import solver_dir, research_dir, results_root, resolve_input
if len(sys.argv) not in (2,3): raise SystemExit('usage: python ladder/edge_rung.py <key> [<config.json>]')
key=sys.argv[1]
config=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else b/(key+'.json')
c=json.loads(config.read_text())
out=results_root(b)/key; research=research_dir(b)
os.environ['SP_RESIDUAL_DUMP_DIR']=str(out/'captures')
sys.path.insert(0,str(research))
sys.argv=[str(research/'compare_saved.py'), '--code-dir',str(solver_dir(b)),
    '--checkpoint',str(resolve_input(c['checkpoint'],config.parent,b)), '--L',str(c['L']), '--n',str(c['n']),
    '--target',str(c['target']), '--pricing-rounds',str(c.get('pricing_rounds',0)), '--min-side','0.001',
    '--screen','--reprice-on-budget','--legacy-fallback','--repair-rounds','-1',
    '--prove','--monitor-format','--case-key',key,'--out',str(out)]
runpy.run_path(str(research/'compare_saved.py'),run_name='__main__')
