"""Failure-only capture. No retry, tolerance changes, or solver mutations."""
import hashlib
import json
from pathlib import Path
import tempfile
import numpy as np
from scipy import sparse


def save_failure(master, raw_weights, raw_dual, weights, dual, residuals, sol):
    root = Path(master.residual_dump_dir)
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='failure-', dir=root))
    sparse.save_npz(out/'cached_matrix.npz', master.A)
    # Keep statistics of the negative dual values, to measure how far rounding makes the
    # gap underestimated (observed at n=17: 261 negatives summing to -1.39e-07; the gap
    # shrinks by rhs times that sum).
    negatives = raw_dual[raw_dual < 0]
    residuals = dict(residuals, neg_dual_count=int(negatives.size),
                     neg_dual_sum=float(negatives.sum()) if negatives.size else 0.0,
                     neg_dual_min=float(negatives.min()) if negatives.size else 0.0)
    # Keep the violation both before and after rounding, to tell the two failure types apart:
    #  type A = rounding amplifies the violation until the check rejects it,
    #  type B = the solution itself already breaks the tolerance.
    # The gap is also recomputed before rounding. Rounding only decreases the gap, so the
    # unrounded value is closer to the true gap.
    try:
        raw_reduced = master.A.T @ raw_dual
        clipped_reduced = master.A.T @ dual
        raw_v = float(max(0.0, float(raw_reduced.max()) - 1.0))
        clip_v = float(max(0.0, float(clipped_reduced.max()) - 1.0))
        residuals = dict(residuals,
                         raw_violation=raw_v, clipped_violation=clip_v,
                         violation_amplification=(clip_v / raw_v) if raw_v > 0 else None,
                         raw_gap=float(raw_weights.sum() - master.rhs*float(raw_dual.sum())
                                       - residuals.get('correction', 0.0)))
        # Two ratios classify the type and complement each other (confirmed on two cases):
        #   type A (rounding)          : divergence ratio ~1,  amplification ~50
        #   type B (solution itself)   : divergence ratio ~50, amplification ~1
        # divergence ratio = raw_violation / HiGHS max_dual_infeasibility.
        # Either ratio alone classifies; both together cross-check each other.
        if master.h is not None:
            try:
                mdi = float(master.h.getInfo().max_dual_infeasibility)
                residuals = dict(residuals, max_dual_infeasibility=mdi,
                                 divergence_ratio=(raw_v / mdi) if mdi > 0 else None,
                                 failure_type=('A (rounding)' if raw_v > 0 and clip_v / raw_v > 10
                                               else 'B (solution itself)' if mdi > 0 and raw_v / mdi > 10
                                               else 'unknown'))
            except Exception as e:
                residuals = dict(residuals, divergence_error=repr(e))
    except Exception as e:
        residuals = dict(residuals, raw_violation_error=repr(e))   # never swallow the error
    arrays = dict(raw_weights=raw_weights, raw_dual=raw_dual,
                  checked_weights=weights, checked_dual=dual,
                  poses=master.poses, rectangles=master.rectangles,
                  atoms=master.atoms, atom_weights=master.atom_weights,
                  atom_lo=master.atom_lo, atom_hi=master.atom_hi,
                  rect_cols=master.rect_cols, atom_cols=master.atom_cols)
    meta = dict(L=master.L, B=master.B, rhs=master.rhs,
                backend=master.backend, atom_mode=master.atom_mode,
                residuals=residuals, thresholds=dict(minimum_slack=2e-7,
                dual=2e-5, absolute_gap=1e-4), certificate_claim=False)
    if master.h is not None:
        h = master.h
        lp, basis = h.getLp(), h.getBasis()
        matrix = lp.a_matrix_
        arrays.update(solver_matrix_start=np.asarray(matrix.start_),
                      solver_matrix_end=np.asarray(matrix.p_end_),
                      solver_matrix_index=np.asarray(matrix.index_),
                      solver_matrix_value=np.asarray(matrix.value_),
                      col_cost=np.asarray(lp.col_cost_),
                      col_lower=np.asarray(lp.col_lower_),
                      col_upper=np.asarray(lp.col_upper_),
                      row_lower=np.asarray(lp.row_lower_),
                      row_upper=np.asarray(lp.row_upper_),
                      raw_col_dual=np.asarray(sol.col_dual),
                      raw_row_value=np.asarray(sol.row_value),
                      basis_col_status=np.asarray([int(x) for x in basis.col_status]),
                      basis_row_status=np.asarray([int(x) for x in basis.row_status]))
        # HiGHS's own measured feasibility. Compared with the configured tolerance (1e-9 in
        # master.py) it shows whether the solver is working at its limit or has room left.
        # Observed with a 1e-8 setting: max_dual_infeasibility 5.7181e-09 (57% of the tolerance).
        try:
            info = h.getInfo()
            meta['solver_info'] = {k: getattr(info, k) for k in (
                'max_dual_infeasibility', 'max_primal_infeasibility',
                'num_dual_infeasibilities', 'num_primal_infeasibilities',
                'simplex_iteration_count', 'objective_function_value',
                'dual_objective_value') if hasattr(info, k)}
            meta['solver_options'] = {n: h.getOptionValue(n)[1] if isinstance(h.getOptionValue(n), tuple)
                                      else h.getOptionValue(n)
                                      for n in ('primal_feasibility_tolerance',
                                                'dual_feasibility_tolerance')}
        except Exception as info_error:
            meta['solver_info_error'] = repr(info_error)   # keep the reason instead of swallowing it
        meta.update(highs_version=h.version(), model_status=str(h.getModelStatus()),
                    matrix_format=str(matrix.format_), shape=[lp.num_row_,lp.num_col_],
                    objective_offset=lp.offset_, objective_sense=int(lp.sense_),
                    basis_valid=basis.valid, primal_valid=sol.value_valid,
                    dual_valid=sol.dual_valid)
        # Binary arrays above are authoritative; text exports aid inspection.
        meta['model_export_status'] = str(h.writeModel(str(out/'model.mps')))
        meta['options_export_status'] = str(h.writeOptions(str(out/'options.txt')))
    elif sol is not None:
        arrays.update(raw_lower_marginals=sol.lower.marginals,
                      raw_upper_marginals=sol.upper.marginals,
                      raw_inequality_marginals=sol.ineqlin.marginals)
        meta['basis_available'] = False  # scipy.linprog does not expose it.
    else:
        # Neither h nor sol: save what exists and record what is missing.
        meta['basis_available'] = False
        meta['solution_object'] = 'absent'
    np.savez_compressed(out/'state.npz', **arrays)
    meta['source_sha256'] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                             for name in ['master.py', 'residual_dump.py']}
    (out/'metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
    # Written last: absence means an incomplete capture.
    (out/'COMPLETE').write_text('Failure captured; no certification claim.\n')
    return out
