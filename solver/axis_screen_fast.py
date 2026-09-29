"""Separable numerical axis screening; final proof remains independent.

Avoid the pose-by-orbit matrix. On axis-aligned squares each rectangle's
intersection area is a product of one-dimensional overlap lengths.
"""
import numpy as np


def axis_values(model,weights):
    coords=np.unique(model.full[:,[0,2]].ravel())
    centers=np.r_[model.L/2,model.L-model.B/2,coords-model.B/2,coords+model.B/2]
    centers=centers[(centers>=model.L/2)&(centers<=model.L-model.B/2)]
    p=np.unique(np.clip((centers-model.L/2)/((model.L-model.B)/2),0.,1.))
    # Match the original matrix's normalization round trip.
    centers=model.L/2+p*((model.L-model.B)/2)
    left=centers[:,None]-model.B/2;right=centers[:,None]+model.B/2
    x=np.maximum(0,np.minimum(right,model.full[None,:,2])-np.maximum(left,model.full[None,:,0]))
    y=np.maximum(0,np.minimum(right,model.full[None,:,3])-np.maximum(left,model.full[None,:,1]))
    rho=np.repeat(np.asarray(weights)/8,8)/model.areas
    # axis_poses uses meshgrid's xy ordering: y outer, x inner.
    values=(y*rho)@x.T
    return p,values.ravel()
