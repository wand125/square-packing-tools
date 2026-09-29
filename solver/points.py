"""Point atoms as extra covering columns alongside the rectangle densities.

The rectangle basis and a point-mass certificate are two different families of
valid inequalities over the same n pairwise-disjoint cores, so their budgets
add:

    sum_i  sum_{p in Q_i} w_p          <=  sum_p w_p       (point family)
    sum_i  integral_{Q_i} rho          <=  total mass      (density family)

Each holds because the cores are disjoint -- an atom lies in at most one of
them, and the densities are nonnegative -- so the sum of the two is valid too.
A certificate then needs n*Gamma > M_point + M_density with Gamma the certified
minimum of the *combined* charge.

What this buys: an existing point certificate can seed a ladder without being
converted into rectangles. Converting is the obvious alternative and it does
not work -- moving each atom's mass onto a small rectangle loses coverage
exactly where the atom sat on a boundary, and measurements put the loss well
past what the budget can absorb. Here the atoms stay atoms; the rectangles only
have to cover what the atoms miss as L grows.

A point column's coefficient for a placement is its weight when the atom lies
inside the placed square, and zero otherwise -- the same 0/1 capture the point
certificates use, scaled by the weight.
"""
import numpy as np

from geometry import Geometry


# The LP's rows must be strictly harder than the checker's boxes, or a row the
# LP satisfies can still sit inside a box the checker rejects. certify.py uses
# the same margin for the same reason: a row satisfied at B/2 - ROW_SHRINK
# implies every leaf box around that centre is covered at B/2 - EPS.
ROW_SHRINK = 5e-4


def capture(poses, L, B, atoms, shrink=ROW_SHRINK):
    """Which atoms each placement captures.

    `poses` are the normalised triples geometry.matrix indexes; `atoms` is an
    (m, 2) array of atom coordinates in container units. Returns an (n, m)
    array that is 1 where the placement covers the atom.

    A placement is the square of side B centred at the pose, rotated by the
    pose's angle. An atom is captured when, in axes parallel to that square,
    both of its offsets from the centre are within B/2 -- the closed square,
    matching how the point certificates charge.
    """
    p = np.asarray(poses, float).reshape(-1, 3)
    a = np.asarray(atoms, float).reshape(-1, 2)
    if not np.isfinite(p).all() or not np.isfinite(a).all():
        raise ValueError('poses and atoms must be finite')
    # theta is the angle as a fraction of pi/4. The rational net's last node
    # sits at 45.0769 degrees -- just past pi/4 by construction, so the net
    # provably covers the whole quarter turn -- which is 1.0017 here. Rejecting
    # that loses the very directions the net exists to reach, so allow the
    # small overshoot the net needs and reject only what is genuinely outside.
    if (np.any(np.abs(p[:, :2]) > 1) or np.any(p[:, 2] < 0)
            or np.any(p[:, 2] > 1.01)):
        raise ValueError('Pose=(normalized cx,cy,theta); xy in [-1,1], theta in [0,1]')

    theta = p[:, 2] * (np.pi / 4)
    c, s = np.cos(theta), np.sin(theta)
    # The pose's xy are fractions of how far the centre may travel at that
    # angle, which is what geometry.matrix indexes; undo that to get the centre.
    reach = (L - B * (np.abs(c) + np.abs(s))) / 2
    cx = L / 2 + p[:, 0] * reach
    cy = L / 2 + p[:, 1] * reach

    dx = a[None, :, 0] - cx[:, None]
    dy = a[None, :, 1] - cy[:, None]
    u = dx * c[:, None] + dy * s[:, None]
    v = -dx * s[:, None] + dy * c[:, None]
    h = B / 2 - shrink
    return ((np.abs(u) <= h) & (np.abs(v) <= h)).astype(float)


def columns(poses, L, B, atoms, weights):
    """Coverage block for point columns: capture scaled by each atom's weight."""
    w = np.asarray(weights, float).reshape(-1)
    if len(w) != len(np.asarray(atoms, float).reshape(-1, 2)):
        raise ValueError('one weight per atom')
    if np.any(w < 0):
        raise ValueError('atom weights must be nonnegative')
    return capture(poses, L, B, atoms) * w[None, :]


def budget(weights):
    """Total mass the point family may spend across n disjoint cores."""
    w = np.asarray(weights, float).reshape(-1)
    if np.any(w < 0):
        raise ValueError('atom weights must be nonnegative')
    return float(w.sum())


def bounds(weights, mode):
    """Lower and upper bounds for the atoms' LP columns.

    `mode` 'fixed' pins each atom at the weight the source certificate gave it,
    so the LP only decides the rectangles and the point family contributes a
    constant budget. 'free' lets the LP move the weights, which costs nothing
    extra to set up -- the columns already carry unit cost, so the objective
    counts atom mass and rectangle mass the same way -- and lets a cheap atom
    be traded for a rectangle that covers more.

    Fixed is the conservative choice: it cannot do worse than the certificate
    it started from, because that assignment stays feasible. Free can do better
    or worse, since moving mass off an atom can open a hole the rectangles then
    have to pay to close.
    """
    w = np.asarray(weights, float).reshape(-1)
    if np.any(w < 0):
        raise ValueError('atom weights must be nonnegative')
    if mode == 'fixed':
        return w.copy(), w.copy()
    if mode == 'free':
        return np.zeros(len(w)), np.full(len(w), np.inf)
    raise ValueError("mode must be 'fixed' or 'free'")
