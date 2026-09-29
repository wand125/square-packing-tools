"""Experimental rectangle-only numerical oracle; independent proof unchanged."""
from time import perf_counter
import numpy as np
from geometry import Geometry
from axis_screen_fast import axis_values
from net_screen_scratch import verify_angle


def separate_global(master,solution,target=1.0005,budget=1000000,max_rows=24,preferred_angles=()):
    if not 1.0001<target<master.rhs-1e-6 or budget<1 or max_rows<1:raise ValueError('invalid search settings')
    if len(getattr(master,'atoms',[])):raise ValueError('rectangle-only experimental oracle')
    start=perf_counter();weights=np.asarray(solution.weights)
    if hasattr(master,'rect_cols'):weights=weights[master.rect_cols]
    active=weights>0;weights=weights[active]
    model=Geometry(master.L,master.B,np.asarray(master.rectangles)[active])
    p,values=axis_values(model,weights);axis_seconds=perf_counter()-start
    poses=[]
    for i in np.argsort(values):
        if values[i]>=target*(1+1e-7) or len(poses)>=max_rows:break
        poses.append([p[i%len(p)],p[i//len(p)],0.])
    order=[]
    for angle in preferred_angles:
        if int(angle)!=angle or not 1<=angle<=200:raise ValueError('invalid preferred angle')
        if angle not in order:order.append(int(angle))
    order.extend(a for a in range(1,201) if a not in order)
    rho=np.repeat(weights/8,8)/model.areas/target;cases=[];unknown=[];nodes=0
    for angle in order:
        if len(poses)>=max_rows:break
        t=83*angle/40000;c,s=(1-t*t)/(1+t*t),2*t/(1+t*t)
        status,visited,leaves,minimum,witness,pending,lower=verify_angle(c,s,master.B,master.L,model.full,rho,budget)
        nodes+=visited;cases.append({'r':angle,'status':int(status),'nodes':int(visited)})
        if status==0:
            e=(master.L-master.B*(c+s))/2;u,v=(witness[:2]-master.L/2)/e;a=2*np.arctan(t)/(np.pi/4)
            if a>1:u,v,a=v,u,2-a
            poses.append(np.clip([u,v,a],[0,0,0],[1,1,1]))
        elif status==-1:unknown.append(angle)
    complete=len(cases)==200 and not unknown and not poses
    poses=np.asarray(poses).reshape(-1,3)
    checked=model.matrix(poses)@weights if len(poses) else np.array([])
    poses=poses[checked<master.rhs-2e-7]
    return poses,{'operation':'global_separation','status':'SCREENED_ALL_NET_CENTERS' if complete else ('COUNTEREXAMPLES' if len(poses) else 'UNRESOLVED'),
      'angles_checked':len(cases)+1,'unknown_angles':unknown,'axis_minimum':float(values.min()),'axis_poses':len(values),
      'axis_seconds':axis_seconds,'new_rows':len(poses),'nodes':int(nodes),'seconds':perf_counter()-start,
      'screening_target':target,'globally_verified':False,'angles':cases}
