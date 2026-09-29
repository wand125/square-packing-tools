"""Schedule numerical rectangle separation; never certify or change LP/proof gates."""
import functools
import inspect
import math
import os


def priority(poses):
    angles=[min(a,2-a) for a in (2*math.atan(83*r/40000)/(math.pi/4) for r in range(1,201))]
    out=[]
    for pose in reversed(poses):
        value=float(pose[2]);ix=min(range(200),key=lambda k:abs(angles[k]-value))
        if abs(angles[ix]-value)<1e-10 and ix+1 not in out:out.append(ix+1)
    return out


def wrap(original):
    if getattr(original,'_batch16_wrapped',False):return original
    sig=inspect.signature(original)
    if tuple(sig.parameters)!=('master','solution','target','budget','max_rows','preferred_angles'):
        raise RuntimeError('unsupported rectangle separation signature')
    @functools.wraps(original)
    def separate(*args,**kwargs):
        bound=sig.bind(*args,**kwargs);bound.apply_defaults();a=bound.arguments;m=a['master']
        state=getattr(m,'_batch16_schedule',None)
        if state is None:
            state=dict(calls=0,preferred=priority(m.poses[-256:]));m._batch16_schedule=state
        state['calls']+=1;audit=state['calls']%8==0
        requested=a['max_rows']
        if requested<1:return original(*args,**kwargs) # retain original invalid-setting handling
        bounded=os.environ.get('SP_SCREEN_AUDIT_BATCH')=='16'
        if bounded and not audit:
            from witness_batches import take
            deferred=take(m,a['solution'],min(16,requested))
            if deferred is not None:
                bad,report=deferred
                report['screen_policy']=dict(name='batch16',call=state['calls'],periodic_full=False,deferred_batch=True)
                return bad,report
        a['max_rows']=max(1000000,requested) if audit else min(16,requested)
        a['preferred_angles']=() if audit else state['preferred']+list(a['preferred_angles'])
        bad,report=original(**a);fallback=False;partial_seconds=0.;partial_nodes=0
        # Filtering can remove all early witnesses. Always finish the full net
        # before allowing an empty result to reach the caller's stopping logic.
        complete=report['angles_checked']==201 and not report['unknown_angles']
        if not len(bad) and not audit and not complete:
            fallback=True;partial_seconds=report['seconds'];partial_nodes=report['nodes']
            a['max_rows']=max(1000000,requested);a['preferred_angles']=()
            bad,report=original(**a)
            report=dict(report);report['seconds']+=partial_seconds;report['nodes']+=partial_nodes
        if report['status']=='SCREENED_ALL_NET_CENTERS' and (len(bad) or report['angles_checked']!=201 or report['unknown_angles']):
            raise RuntimeError('incomplete screen cannot claim full-net clearance')
        if len(bad):
            fresh=priority(bad);state['preferred']=fresh+[r for r in state['preferred'] if r not in fresh]
        report=dict(report);report['screen_policy']=dict(name='batch16',call=state['calls'],periodic_full=audit,empty_result_full_fallback=fallback,max_rows=a['max_rows'],partial_seconds=partial_seconds)
        if bounded:
            from witness_batches import admit
            bad,report=admit(m,bad,report,min(16,requested))
        return bad,report
    separate._batch16_wrapped=True
    return separate
