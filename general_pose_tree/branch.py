"""Exact minimum core charge over all centres for one angle row (generalizes PL45-PL47).

Problem.  Fixed core side B, fixed core orientation theta = 2*arctan(t)
(t = p/q, 0 <= t <= 1), measure mu (ordinary points + k-of-m threshold
features, see measure.py), centre domain the closed square [r, L-r]^2.
Compute  min_{centre in domain} charge(closed core at centre)  exactly.

Frame.  Everything is done in the core frame, scaled to integers:
    U = Q*(C x + S y),   V = Q*(-S x + C y),   C = q^2-p^2, S = 2pq, R = q^2+p^2,
with Q a common denominator making all data integral.  A site P is captured by
the closed core centred at c iff |U_c - U_P| <= H and |V_c - V_P| <= H with
H = Q*R*B/2, i.e. the capture set of each site is a closed axis-parallel
rectangle in (U,V).  The centre domain becomes a rotated square (an open
convex polygon after taking its interior).  Boxes of the branch-and-bound are
axis-parallel in (U,V) - equivalently, rotated rectangles in the container
frame - which makes the site classification exact and tight.

Boundary handling (as in Kleddamag's PROOF.md).  The charge is a nonnegative
combination of indicators of closed sets (finite unions of intersections of
closed rectangles), hence upper semicontinuous.  Every point of the closed
domain is a limit of generic interior points (points on no rectangle edge),
so charge(x) >= limsup of generic values near x >= inf over generic values.
Therefore min over the closed domain = min over the open cells of the edge
arrangement intersected with the open domain.  The solver works only with
open boxes / open cells:
  * surely-in  : closed box contained in the closed capture rectangle,
  * surely-out : open box disjoint from the closed capture rectangle,
  * otherwise undetermined (some rectangle edge crosses the open box).
Lower bound of a box = surely-in ordinary weights + features whose surely-in
count already reaches k.  Leaves (few undetermined sites) are solved exactly:
the undetermined rectangle edges cut the box into a grid of open cells on each
of which every membership is constant; a cell counts iff it meets the open
domain (exact separating-axis test on 4 axes).

Only integer comparisons enter accepted inequalities; there is no float.
"""
from fractions import Fraction as F
from math import lcm
import heapq
import time


class RowSolver:
    def __init__(self, measure, L, B, t, r):
        L, B, t, r = F(L), F(B), F(t), F(r)
        if not (0 <= t <= 1):
            raise ValueError("need 0 <= t <= 1")
        if not (0 < r < L / 2):
            raise ValueError("empty centre domain")
        self.measure, self.L, self.B, self.t, self.r = measure, L, B, t, r
        p, q = t.numerator, t.denominator
        C, S, R = q * q - p * p, 2 * p * q, q * q + p * p
        self.C, self.S, self.R = C, S, R
        D = measure.D
        Hf = R * B / 2
        Q = lcm(D, Hf.denominator, r.denominator, L.denominator)
        self.Q = Q
        H = Hf * Q
        assert H.denominator == 1
        H = int(H)
        self.H = H
        # relevant sites -> local indices
        rel = measure.relevant_sites()
        self.global_index = rel
        loc = {g: i for i, g in enumerate(rel)}
        mult = Q // D
        self.ulo, self.uhi, self.vlo, self.vhi, self.ow = [], [], [], [], []
        for g in rel:
            X, Y = measure.coords[g]
            u = (C * X + S * Y) * mult
            v = (-S * X + C * Y) * mult
            self.ulo.append(u - H); self.uhi.append(u + H)
            self.vlo.append(v - H); self.vhi.append(v + H)
            self.ow.append(measure.weights[g])
        self.fk, self.fw, self.fsites = [], [], []
        self.site_feats = [[] for _ in rel]
        for f in measure.features:
            fid = len(self.fk)
            self.fk.append(f.k); self.fw.append(f.w)
            ls = [loc[g] for g in f.sites]
            self.fsites.append(ls)
            for i in ls:
                self.site_feats[i].append(fid)
        # domain polygon (rotated square) in integer (U,V)
        rQ, LrQ = int(r * Q), int((L - r) * Q)
        corners = [(rQ, rQ), (LrQ, rQ), (LrQ, LrQ), (rQ, LrQ)]
        self.poly = [(C * x + S * y, -S * x + C * y) for x, y in corners]
        us = [a for a, _ in self.poly]; vs = [b for _, b in self.poly]
        self.PU0, self.PU1, self.PV0, self.PV1 = min(us), max(us), min(vs), max(vs)
        # projections onto container axes: C U - S V = Q R^2 x ; S U + C V = Q R^2 y
        self.XL, self.XH = R * R * rQ, R * R * LrQ

    # ------------------------------------------------------------ geometry
    def meets_domain(self, U0, U1, V0, V1):
        """Exact: open box (U0,U1)x(V0,V1) meets the open domain polygon (SAT, 4 axes)."""
        if not (U0 < self.PU1 and self.PU0 < U1 and V0 < self.PV1 and self.PV0 < V1):
            return False
        C, S = self.C, self.S
        if not (C * U0 - S * V1 < self.XH and self.XL < C * U1 - S * V0):
            return False
        if not (S * U0 + C * V0 < self.XH and self.XL < S * U1 + C * V1):
            return False
        return True

    def classify(self, i, U0, U1, V0, V1):
        """1 surely-in (closed box inside closed rectangle), 0 surely-out (open box
        misses closed rectangle), None undetermined."""
        a, b, c, d = self.ulo[i], self.uhi[i], self.vlo[i], self.vhi[i]
        if U1 <= a or U0 >= b or V1 <= c or V0 >= d:
            return 0
        if a <= U0 and U1 <= b and c <= V0 and V1 <= d:
            return 1
        return None

    # ------------------------------------------------------------ nodes
    def root(self):
        box = (self.PU0, self.PU1, self.PV0, self.PV1)
        openf = {f: (0, len(s)) for f, s in enumerate(self.fsites)}
        return self.refine(box, list(range(len(self.ulo))), 0, openf)

    def refine(self, box, undet, base, openf):
        """Classify the parent's undetermined sites on `box`; return (base, undet, openf)."""
        U0, U1, V0, V1 = box
        ulo, uhi, vlo, vhi, ow, sf = self.ulo, self.uhi, self.vlo, self.vhi, self.ow, self.site_feats
        new_und = []
        din, dund = {}, {}
        for i in undet:
            a, b, c, d = ulo[i], uhi[i], vlo[i], vhi[i]
            if U1 <= a or U0 >= b or V1 <= c or V0 >= d:
                for f in sf[i]:
                    if f in openf:
                        dund[f] = dund.get(f, 0) + 1
            elif a <= U0 and U1 <= b and c <= V0 and V1 <= d:
                base += ow[i]
                for f in sf[i]:
                    if f in openf:
                        din[f] = din.get(f, 0) + 1
                        dund[f] = dund.get(f, 0) + 1
            else:
                new_und.append(i)
        if dund:
            openf = dict(openf)
            fk, fw = self.fk, self.fw
            for f, du in dund.items():
                ic, uc = openf[f]
                ic += din.get(f, 0)
                uc -= du
                if ic >= fk[f]:
                    base += fw[f]
                    del openf[f]
                elif ic + uc < fk[f]:
                    del openf[f]
                else:
                    openf[f] = (ic, uc)
        return base, new_und, openf

    def split(self, box, undet):
        U0, U1, V0, V1 = box
        eu, ev = [], []
        for i in undet:
            for x in (self.ulo[i], self.uhi[i]):
                if U0 < x < U1:
                    eu.append(x)
            for y in (self.vlo[i], self.vhi[i]):
                if V0 < y < V1:
                    ev.append(y)
        # an undetermined site always has an edge strictly inside the box
        assert eu or ev
        if len(eu) >= len(ev):
            eu.sort(); m = eu[len(eu) // 2]
            return (U0, m, V0, V1), (m, U1, V0, V1)
        ev.sort(); m = ev[len(ev) // 2]
        return (U0, U1, V0, m), (U0, U1, m, V1)

    def leaf(self, box, undet, base, openf, want_cell=False):
        """Exact min over open cells inside the open box that meet the open domain.
        Returns (value or None, cell, cells_evaluated)."""
        U0, U1, V0, V1 = box
        ucuts = sorted({U0, U1} | {x for i in undet for x in (self.ulo[i], self.uhi[i]) if U0 < x < U1})
        vcuts = sorted({V0, V1} | {y for i in undet for y in (self.vlo[i], self.vhi[i]) if V0 < y < V1})
        umask = []
        for a, b in zip(ucuts, ucuts[1:]):
            m = 0
            for j, i in enumerate(undet):
                if self.ulo[i] <= a and b <= self.uhi[i]:
                    m |= 1 << j
            umask.append(m)
        vmask = []
        for a, b in zip(vcuts, vcuts[1:]):
            m = 0
            for j, i in enumerate(undet):
                if self.vlo[i] <= a and b <= self.vhi[i]:
                    m |= 1 << j
            vmask.append(m)
        pos = {i: j for j, i in enumerate(undet)}
        feats = []
        for f, (ic, uc) in openf.items():
            fm = 0
            for i in self.fsites[f]:
                if i in pos:
                    fm |= 1 << pos[i]
            if fm:
                feats.append((fm, self.fk[f] - ic, self.fw[f]))
        bw = [self.ow[i] for i in undet]
        cache = {}
        best = None; cell = None; n = 0
        for iu, (a, b) in enumerate(zip(ucuts, ucuts[1:])):
            for iv, (c, d) in enumerate(zip(vcuts, vcuts[1:])):
                if not self.meets_domain(a, b, c, d):
                    continue
                n += 1
                m = umask[iu] & vmask[iv]
                val = cache.get(m)
                if val is None:
                    val = base
                    for j, w in enumerate(bw):
                        if m >> j & 1:
                            val += w
                    for fm, need, w in feats:
                        if bin(m & fm).count("1") >= need:
                            val += w
                    cache[m] = val
                if best is None or val < best:
                    best, cell = val, (a, b, c, d)
        return best, cell, n

    # ------------------------------------------------------------ witness
    def witness(self, cell):
        """Exact container-frame point interior to (open cell) cap (open domain)."""
        a, b, c, d = cell
        pts = [(F(a), F(c)), (F(b), F(c)), (F(b), F(d)), (F(a), F(d))]
        C, S = self.C, self.S
        # half-planes: XL < C U - S V < XH and XL < S U + C V < XH
        planes = [((C, -S), self.XL, 1), ((C, -S), self.XH, -1), ((S, C), self.XL, 1), ((S, C), self.XH, -1)]
        for (gx, gy), lim, sgn in planes:
            val = lambda p: sgn * (gx * p[0] + gy * p[1] - lim)
            out = []
            for k in range(len(pts)):
                P, Qp = pts[k], pts[(k + 1) % len(pts)]
                vp, vq = val(P), val(Qp)
                if vp >= 0:
                    out.append(P)
                if (vp > 0 > vq) or (vp < 0 < vq):
                    s = vp / (vp - vq)
                    out.append((P[0] + s * (Qp[0] - P[0]), P[1] + s * (Qp[1] - P[1])))
            pts = out
        assert len(pts) >= 3
        # average of distinct vertices of a nondegenerate convex polygon is interior
        uniq = list(dict.fromkeys(pts))
        U = sum(p[0] for p in uniq) / len(uniq)
        V = sum(p[1] for p in uniq) / len(uniq)
        assert a < U < b and c < V < d
        k = self.Q * self.R * self.R
        x, y = (C * U - S * V) / k, (S * U + C * V) / k
        assert self.r < x < self.L - self.r and self.r < y < self.L - self.r
        return x, y

    # ------------------------------------------------------------ solvers
    def minimize(self, leaf_size=10, node_limit=None, verify_witness=True):
        """Exact minimum by best-first branch and bound.  All nodes with lower
        bound < final minimum are expanded (best-first order)."""
        t0 = time.monotonic()
        st = dict(boxes_expanded=0, leaves=0, max_depth=0, cells=0, nodes_created=1,
                  outside_pruned=0, bound_pruned=0, max_heap=1)
        base, und, openf = self.root()
        heap = [(base, 0, (self.PU0, self.PU1, self.PV0, self.PV1), und, openf, 0)]
        seq = 1
        best = None; best_cell = None
        while heap:
            lb, _, box, und, openf, depth = heapq.heappop(heap)
            if best is not None and lb >= best:
                st["bound_pruned"] += 1 + len(heap)
                break
            st["max_depth"] = max(st["max_depth"], depth)
            if len(und) <= leaf_size:
                v, cell, n = self.leaf(box, und, lb, openf)
                st["leaves"] += 1; st["cells"] += n
                if v is not None and (best is None or v < best):
                    best, best_cell = v, cell
                continue
            st["boxes_expanded"] += 1
            if node_limit and st["boxes_expanded"] > node_limit:
                raise RuntimeError("node limit")
            for child in self.split(box, und):
                if not self.meets_domain(*child):
                    st["outside_pruned"] += 1
                    continue
                cb, cu, co = self.refine(child, und, lb, openf)
                st["nodes_created"] += 1
                if best is not None and cb >= best:
                    st["bound_pruned"] += 1
                    continue
                heapq.heappush(heap, (cb, seq, child, cu, co, depth + 1)); seq += 1
            st["max_heap"] = max(st["max_heap"], len(heap))
        assert best is not None
        x, y = self.witness(best_cell)
        res = dict(minimum=best, witness=[str(x), str(y)], seconds=time.monotonic() - t0, **st)
        if verify_witness:
            direct = self.measure.charge_at(x, y, self.B, self.t)
            assert direct == best, (direct, best)
            res["witness_replayed"] = True
        return res

    def certify(self, target, leaf_size=10):
        """Prove min >= target (depth-first; prune boxes with lower bound >= target).
        Returns dict with ok flag; on failure a witness with charge < target."""
        t0 = time.monotonic()
        st = dict(boxes_expanded=0, leaves=0, max_depth=0, cells=0, nodes_created=1,
                  outside_pruned=0, bound_pruned=0)
        base, und, openf = self.root()
        stack = [((self.PU0, self.PU1, self.PV0, self.PV1), und, base, openf, 0)]
        leaf_min = None
        while stack:
            box, und, lb, openf, depth = stack.pop()
            if lb >= target:
                st["bound_pruned"] += 1
                continue
            st["max_depth"] = max(st["max_depth"], depth)
            if len(und) <= leaf_size:
                v, cell, n = self.leaf(box, und, lb, openf)
                st["leaves"] += 1; st["cells"] += n
                if v is not None:
                    leaf_min = v if leaf_min is None else min(leaf_min, v)
                    if v < target:
                        x, y = self.witness(cell)
                        return dict(ok=False, value=v, witness=[str(x), str(y)],
                                    seconds=time.monotonic() - t0, **st)
                continue
            st["boxes_expanded"] += 1
            for child in self.split(box, und):
                if not self.meets_domain(*child):
                    st["outside_pruned"] += 1
                    continue
                cb, cu, co = self.refine(child, und, lb, openf)
                st["nodes_created"] += 1
                stack.append((child, cu, cb, co, depth + 1))
        return dict(ok=True, target=target, seconds=time.monotonic() - t0, **st)


def brute_min(solver):
    """Independent exact minimum (no branch and bound): full grid of ALL rectangle
    edges over the domain's bounding box, each open cell tested against the open
    domain and evaluated by direct membership.  Only for small tests."""
    us = sorted({solver.PU0, solver.PU1} | {x for i in range(len(solver.ulo)) for x in (solver.ulo[i], solver.uhi[i]) if solver.PU0 < x < solver.PU1})
    vs = sorted({solver.PV0, solver.PV1} | {y for i in range(len(solver.vlo)) for y in (solver.vlo[i], solver.vhi[i]) if solver.PV0 < y < solver.PV1})
    best = None
    for a, b in zip(us, us[1:]):
        for c, d in zip(vs, vs[1:]):
            if not solver.meets_domain(a, b, c, d):
                continue
            x, y = solver.witness((a, b, c, d))
            v = solver.measure.charge_at(x, y, solver.B, solver.t)
            best = v if best is None else min(best, v)
    return best
