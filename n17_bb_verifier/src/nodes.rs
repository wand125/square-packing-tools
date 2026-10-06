//! Independent interval certificate node checks, translated from the standing verifier.
use crate::exact::{
    Box4, Plane, Point, Q, Span, box_contains, box_max_linear, clip_cell_to_box, contract, cos_sin,
    enclosed_max, gap_lower, half_pi_multiple, hp_lo, interval_mul, most_abs, parse, plane_box_min,
    sqrt_upper,
};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};

pub(crate) type Result<T> = std::result::Result<T, String>;
pub(crate) type Counts = BTreeMap<String, u64>;

/// Immutable frame shared by node checks.
pub(crate) struct NodeVerifier {
    pub(crate) v3: bool,
    pub(crate) trig_keys: std::collections::BTreeSet<String>,
    pub(crate) cells: Vec<Vec<Point>>,
    pub(crate) cap: Q,
    pub(crate) pairs: Vec<(usize, usize)>,
    pub(crate) root_angles: Vec<Span>,
    pub(crate) root_boxes: Vec<Box4>,
}

pub(crate) fn arr(v: &Value) -> Result<&Vec<Value>> {
    v.as_array().ok_or_else(|| "expected array".into())
}
pub(crate) fn index(v: &Value) -> Result<usize> {
    v.as_u64()
        .and_then(|x| usize::try_from(x).ok())
        .ok_or_else(|| "invalid index".into())
}
fn rat(v: &Value) -> Result<Q> {
    parse(v.as_str().ok_or("expected rational string")?)
}
pub(crate) fn qs<const N: usize>(v: &Value) -> Result<[Q; N]> {
    let values = arr(v)?.iter().map(rat).collect::<Result<Vec<_>>>()?;
    values
        .try_into()
        .map_err(|_| "wrong rational array length".into())
}
fn boxes(v: &Value) -> Result<Vec<Box4>> {
    arr(v)?.iter().map(qs).collect()
}
pub(crate) fn tick(counts: &mut Counts, key: &str) {
    *counts.entry(key.to_owned()).or_default() += 1;
}
pub(crate) fn at<T>(xs: &[T], i: usize) -> Result<&T> {
    xs.get(i).ok_or_else(|| "index out of range".into())
}

pub(crate) struct NodeState {
    pub(crate) angles: Vec<Span>,
    pub(crate) windows: HashMap<usize, Span>,
}
impl NodeState {
    fn new(node: &Value) -> Result<Self> {
        let angles: Vec<Span> = arr(&node["angles"])?
            .iter()
            .map(qs)
            .collect::<Result<_>>()?;
        // `prepared` in the reference parses this metadata before any closure
        // shortcut, including metadata attached to a non-Taylor closed leaf.
        if let Some(taylor) = node.get("taylor") {
            let centres = arr(&taylor["centres"])?
                .iter()
                .map(rat)
                .collect::<Result<Vec<_>>>()?;
            if centres.len() != angles.len() {
                return Err("Taylor centre count does not match angles".into());
            }
        }
        if let Some(final_boxes) = node.get("final").filter(|value| !value.is_null()) {
            boxes(final_boxes)?;
        }
        let mut windows = HashMap::new();
        for w in arr(&node["windows"])? {
            windows.insert(index(&w[0])?, [rat(&w[1])?, rat(&w[2])?]);
        }
        Ok(Self { angles, windows })
    }
}
struct PairPlanes {
    planes: Vec<Vec<Plane>>,
    pieces: Vec<[Q; 3]>,
    dx: Span,
    dy: Span,
}
#[derive(Clone)]
struct Row {
    columns: Vec<usize>,
    coefficients: Vec<Q>,
    rhs: Q,
    vacuous: bool,
}
#[derive(Default)]
// The reference freezes a pair at its first row use in a round, even when
// subsequent bound checks use tighter boxes. Thus a cut row is also immutable
// within that round. Caches must never cross round or node boundaries.
struct RoundCache {
    pairs: HashMap<usize, PairPlanes>,
    rows: HashMap<usize, Row>,
}

fn pieces_cover(pieces: &[[Q; 3]], angles: [&Span; 2], window: Option<&Span>) -> bool {
    let mut sorted = pieces.to_vec();
    sorted.sort();
    let mut merged: Vec<Span> = Vec::new();
    for [lo, hi, _] in sorted {
        if let Some(last) = merged.last_mut()
            && lo <= last[1]
        {
            last[1] = last[1].clone().max(hi);
            continue;
        }
        merged.push([lo, hi]);
    }
    let covered = |lo: &Q, hi: &Q| merged.iter().any(|[a, b]| a <= lo && hi <= b);
    let two_pi = half_pi_multiple(4);
    for [a, b] in angles {
        for k in 0..4 {
            let m = half_pi_multiple(k);
            let s = [a.clone() + m[0].clone(), b.clone() + m[1].clone()];
            if let Some(win) = window {
                for turns in -1..=1 {
                    let shifted = match turns {
                        -1 => [
                            s[0].clone() - two_pi[1].clone(),
                            s[1].clone() - two_pi[0].clone(),
                        ],
                        1 => [
                            s[0].clone() + two_pi[0].clone(),
                            s[1].clone() + two_pi[1].clone(),
                        ],
                        _ => s.clone(),
                    };
                    let lo = shifted[0].clone().max(win[0].clone());
                    let hi = shifted[1].clone().min(win[1].clone());
                    if lo <= hi && !covered(&lo, &hi) {
                        return false;
                    }
                }
            } else if !covered(&s[0], &s[1]) {
                return false;
            }
        }
    }
    true
}
fn piece_planes(piece: &[Q; 3], gap: &Q, dx: &Span, dy: &Span) -> Result<Vec<Plane>> {
    let [lo, hi, m] = piece;
    if !(lo <= m && m <= hi) {
        return Err("P3: piece point outside interval".into());
    }
    let reach = most_abs(&dx[0], &dx[1]) + most_abs(&dy[0], &dy[1]);
    let mut planes = Vec::new();
    if hi.clone() - lo.clone() < hp_lo() {
        let x = (m.clone() - lo.clone()).max(hi.clone() - m.clone());
        let factor = Q::from(1) - x.clone() * x / 2;
        for (angle, c) in [(lo, Q::from(1)), (hi, Q::from(1)), (m, factor)] {
            let base = gap.clone() * c;
            let [cl, ch, sl, sh] = cos_sin(angle);
            if enclosed_max(&[cl.clone(), ch.clone()], &[sl.clone(), sh.clone()], dx, dy) < base {
                continue;
            }
            let nx = (cl.clone() + ch.clone()) / 2;
            let ny = (sl.clone() + sh.clone()) / 2;
            let eps = (ch - cl).max(sh - sl);
            let rhs = base - eps * reach.clone();
            if box_max_linear(&nx, &ny, dx, dy) >= rhs {
                planes.push([nx, ny, rhs]);
            }
        }
    } else {
        let [cl, ch, sl, sh] = cos_sin(m);
        let tau: Q = (m.clone() - lo.clone()).max(hi.clone() - m.clone()) / 2;
        let p = interval_mul(&[-sh.clone(), -sl.clone()], dx);
        let p2 = interval_mul(&[cl.clone(), ch.clone()], dy);
        let spread = most_abs(
            &(p[0].clone() + p2[0].clone()),
            &(p[1].clone() + p2[1].clone()),
        );
        let ax = most_abs(&dx[0], &dx[1]);
        let ay = most_abs(&dy[0], &dy[1]);
        let length = sqrt_upper(&(ax.clone() * ax + ay.clone() * ay));
        let nx = (cl.clone() + ch.clone()) / 2;
        let ny = (sl.clone() + sh.clone()) / 2;
        let eps = (ch - cl).max(sh - sl);
        let offset = tau.clone() * 2 * (spread + tau * length) + eps * reach;
        let rhs = gap.clone() - offset;
        if box_max_linear(&nx, &ny, dx, dy) >= rhs {
            planes.push([nx, ny, rhs]);
        }
    }
    Ok(planes)
}
impl NodeVerifier {
    fn pair_planes(
        &self,
        state: &NodeState,
        record: &Value,
        p: usize,
        bounds: &[Box4],
    ) -> Result<PairPlanes> {
        let &(i, j) = at(&self.pairs, p)?;
        let bi = at(bounds, i)?;
        let bj = at(bounds, j)?;
        let dx = [bj[0].clone() - bi[1].clone(), bj[1].clone() - bi[0].clone()];
        let dy = [bj[2].clone() - bi[3].clone(), bj[3].clone() - bi[2].clone()];
        let pieces = arr(&record["pairs"][p.to_string()])?
            .iter()
            .map(qs)
            .collect::<Result<Vec<[Q; 3]>>>()?;
        let ai = at(&state.angles, i)?;
        let aj = at(&state.angles, j)?;
        if !pieces_cover(&pieces, [ai, aj], state.windows.get(&p)) {
            return Err("P2: pieces do not cover normals".into());
        }
        let gap = gap_lower(&ai[0], &ai[1], &aj[0], &aj[1]);
        let planes = pieces
            .iter()
            .map(|piece| piece_planes(piece, &gap, &dx, &dy))
            .collect::<Result<_>>()?;
        Ok(PairPlanes {
            planes,
            pieces,
            dx,
            dy,
        })
    }
    fn row(
        &self,
        state: &NodeState,
        record: &Value,
        bounds: &[Box4],
        reference: &Value,
        cache: &mut RoundCache,
        counts: &mut Counts,
    ) -> Result<Row> {
        let kind = reference[0].as_str().ok_or("row reference kind missing")?;
        if kind == "c" {
            let s = index(&reference[1])?;
            let e = index(&reference[2])?;
            let cell = at(&self.cells, s)?;
            let start = at(cell, e)?;
            let end = at(cell, (e + 1) % cell.len())?;
            let a = end[1].clone() - start[1].clone();
            let b = start[0].clone() - end[0].clone();
            let rhs = a.clone() * start[0].clone() + b.clone() * start[1].clone();
            return Ok(Row {
                columns: vec![2 * s, 2 * s + 1],
                coefficients: vec![a, b],
                rhs,
                vacuous: false,
            });
        }
        if kind == "w" {
            return Err("wall row in interval certificate".into());
        }
        let cut_index = index(&reference[1])?;
        if !cache.rows.contains_key(&cut_index) {
            let cut = at(arr(&record["cuts"])?, cut_index)?;
            if arr(cut)?.len() != 4 {
                return Err("unsupported cut shape".into());
            }
            let pair_index = index(&cut[0])?;
            let direction = [rat(&cut[1])?, rat(&cut[2])?];
            let cut_rhs = rat(&cut[3])?;
            if let std::collections::hash_map::Entry::Vacant(entry) = cache.pairs.entry(pair_index)
            {
                entry.insert(self.pair_planes(state, record, pair_index, bounds)?);
            }
            let pair = cache.pairs.get(&pair_index).ok_or("missing pair cache")?;
            let least = pair
                .planes
                .iter()
                .flatten()
                .filter_map(|plane| plane_box_min(&direction, plane, &pair.dx, &pair.dy))
                .min();
            if least.as_ref().is_some_and(|least| &cut_rhs > least) {
                return Err(format!(
                    "C2: cut {cut_index} of pair {pair_index} exceeds exact plane minimum"
                ));
            }
            let &(i, j) = at(&self.pairs, pair_index)?;
            cache.rows.insert(
                cut_index,
                Row {
                    columns: vec![2 * i, 2 * i + 1, 2 * j, 2 * j + 1],
                    coefficients: vec![
                        direction[0].clone(),
                        direction[1].clone(),
                        -direction[0].clone(),
                        -direction[1].clone(),
                    ],
                    rhs: -cut_rhs,
                    vacuous: least.is_none(),
                },
            );
        }
        let row = cache
            .rows
            .get(&cut_index)
            .ok_or("missing row cache")?
            .clone();
        // The Python receipt counts references, not distinct validated cuts.
        if row.vacuous {
            tick(counts, "vacuous_cut");
        }
        tick(counts, "cut_ok");
        Ok(row)
    }
    fn combination(
        &self,
        state: &NodeState,
        record: &Value,
        bounds: &[Box4],
        multipliers: &Value,
        cost: Option<(usize, Q)>,
        tracking: (&mut RoundCache, &mut Counts),
    ) -> Result<Q> {
        let (cache, counts) = tracking;
        let mut combined = vec![Q::from(0); 2 * self.cells.len()];
        if let Some((col, value)) = cost {
            *combined.get_mut(col).ok_or("cost column out of range")? += value;
        }
        let mut right = Q::from(0);
        for entry in arr(multipliers)? {
            let y = rat(&entry[1])?;
            if y < 0 {
                return Err("C3/C4: negative multiplier".into());
            }
            let row = self.row(state, record, bounds, &entry[0], cache, counts)?;
            for (col, coefficient) in row.columns.iter().zip(row.coefficients) {
                *combined.get_mut(*col).ok_or("row column out of range")? +=
                    y.clone() * coefficient;
            }
            right += y * row.rhs;
        }
        let mut least = Q::from(0);
        for (col, c) in combined.into_iter().enumerate() {
            let b = at(bounds, col / 2)?;
            let slot = 2 * (col % 2) + usize::from(c < 0);
            least += c * b[slot].clone();
        }
        Ok(least - right)
    }
    fn check_bounds(
        &self,
        state: &NodeState,
        node: &Value,
        record: &Value,
        bounds: &[Box4],
        cache: &mut RoundCache,
        counts: &mut Counts,
    ) -> Result<Option<Vec<Box4>>> {
        let mut current = bounds.to_vec();
        if let Some(entries) = record.get("bounds") {
            for entry in arr(entries)? {
                let col = index(&entry[0])?;
                let sign = entry[1].as_i64().ok_or("invalid bound sign")?;
                let value = rat(&entry[2])?;
                let bound = self.combination(
                    state,
                    record,
                    &current,
                    &entry[3],
                    Some((col, Q::from(sign))),
                    (cache, counts),
                )?;
                if value > bound {
                    return Err(format!(
                        "C4: bound on column {col} sign {sign} exceeds combination minimum"
                    ));
                }
                let slot = 2 * (col % 2) + usize::from(sign <= 0);
                current
                    .get_mut(col / 2)
                    .ok_or("bound column out of range")?[slot] =
                    if sign > 0 { value } else { -value };
                tick(counts, "bound_ok");
            }
        }
        if record["emptied"] == "bounds" {
            if !current.iter().any(|b| b[0] > b[1] || b[2] > b[3]) {
                return Err("C5: emptied by bounds but no bound crossed".into());
            }
            if node["closed"] != "obbt" {
                return Err("C5: emptied but not closed obbt".into());
            }
            tick(counts, "closed_obbt_ok");
            return Ok(None);
        }
        let mut tightened = Vec::new();
        for (s, cell) in self.cells.iter().enumerate() {
            if let Some(clipped) = clip_cell_to_box(cell, at(&current, s)?) {
                tightened.push(clipped);
            } else {
                if record["emptied"] != "cell" || node["closed"] != "obbt" {
                    return Err("C5: box misses cell but not closed obbt/cell".into());
                }
                tick(counts, "closed_obbt_ok");
                return Ok(None);
            }
        }
        if record["emptied"] == "cell" {
            return Err("C5: emptied cell but every box meets cell".into());
        }
        let Some(next) = record.get("next") else {
            return Ok(Some(if self.v3 { current } else { bounds.to_vec() }));
        };
        let following = boxes(next)?;
        for (s, b) in tightened.iter().enumerate() {
            if !box_contains(at(&following, s)?, b) {
                return Err("B2: next box too small".into());
            }
        }
        Ok(Some(following))
    }
    fn check_closed_pair(
        &self,
        state: &NodeState,
        record: &Value,
        bounds: &[Box4],
        counts: &mut Counts,
    ) -> Result<()> {
        let p = index(&record["closed_pair"][0])?;
        let kind = record["closed_pair"][1]
            .as_str()
            .ok_or("invalid closure kind")?;
        let &(i, j) = at(&self.pairs, p)?;
        let bi = at(bounds, i)?;
        let bj = at(bounds, j)?;
        let dx = [bj[0].clone() - bi[1].clone(), bj[1].clone() - bi[0].clone()];
        let dy = [bj[2].clone() - bi[3].clone(), bj[3].clone() - bi[2].clone()];
        match kind {
            "disc" => {
                let ax = most_abs(&dx[0], &dx[1]);
                let ay = most_abs(&dy[0], &dy[1]);
                if ax.clone() * ax + ay.clone() * ay >= 1 {
                    return Err("C1: disc closure has max distance squared >= 1".into());
                }
                tick(counts, "closed_disc_ok");
            }
            "pair" => {
                if self
                    .pair_planes(state, record, p, bounds)?
                    .planes
                    .iter()
                    .any(|planes| !planes.is_empty())
                {
                    return Err("C1: pair closure has possible plane".into());
                }
                tick(counts, "closed_pair_ok");
            }
            _ => return Err("unknown pair closure".into()),
        }
        Ok(())
    }
    fn check_open(
        &self,
        state: &NodeState,
        node: &Value,
        previous: &[Box4],
        counts: &mut Counts,
    ) -> Result<()> {
        let final_boxes = boxes(&node["final"])?;
        for (s, b) in previous.iter().enumerate() {
            if !box_contains(at(&final_boxes, s)?, b) {
                return Err("B2: final box too small".into());
            }
        }
        if node["closed"] == "angle" || node["split"].get("tighten").is_some() {
            if final_boxes.len() != self.cells.len() {
                return Err("B2: wrong final box count".into());
            }
            return self.check_eliminations(state, node, previous, counts);
        }
        if let Some(split) = node["split"].get("pair") {
            let p = index(&split[0])?;
            let rounds = arr(&node["rounds"])?;
            let record = rounds.last().ok_or("pair split missing round")?;
            let bounds = boxes(&record["boxes"])?;
            let pair = self.pair_planes(state, record, p, &bounds)?;
            let wins = arr(&split[1])?
                .iter()
                .map(qs)
                .collect::<Result<Vec<Span>>>()?;
            for (planes, [lo, hi, _]) in pair.planes.iter().zip(&pair.pieces) {
                if !planes.is_empty() && !wins.iter().any(|[a, b]| a <= lo && hi <= b) {
                    return Err("P4: pair split leaves possible piece uncovered".into());
                }
            }
            tick(counts, "pair_split_ok");
        } else {
            tick(counts, "angle_split_ok");
        }
        tick(counts, "open_ok");
        Ok(())
    }
    fn check_node_inner(
        &self,
        node: &Value,
        parent: Option<&Value>,
        counts: &mut Counts,
    ) -> Result<()> {
        if !self.v3 && (node["closed"] == "angle" || node["split"].get("tighten").is_some()) {
            return Err("schema: v3 feature in v1 certificate".into());
        }
        if self.v3 && node.get("taylor").is_some() {
            return Err("schema: Taylor node in v3".into());
        }
        let state = NodeState::new(node)?;
        if state.angles.len() != self.cells.len() {
            return Err("angle count does not match cells".into());
        }
        let inherited = if let Some(parent) = parent {
            boxes(&parent["final"])?
        } else {
            if state.angles != self.root_angles || !arr(&node["windows"])?.is_empty() {
                return Err("T1: root angles or windows wrong".into());
            }
            self.root_boxes.clone()
        };
        let rounds = arr(&node["rounds"])?;
        if rounds.is_empty() {
            if node["closed"] != "cell" {
                return Err("no rounds without cell closure".into());
            }
            for (s, cell) in self.cells.iter().enumerate() {
                if contract(cell, at(&inherited, s)?, at(&state.angles, s)?, &self.cap).is_none() {
                    tick(counts, "closed_cell_ok");
                    return Ok(());
                }
            }
            return Err("C1: cell closure but all contracted boxes nonempty".into());
        }
        let mut previous: Vec<Box4> = Vec::new();
        for (r, record) in rounds.iter().enumerate() {
            let bounds = boxes(&record["boxes"])?;
            if bounds.len() != self.cells.len() {
                return Err("box count does not match cells".into());
            }
            for (s, cell) in self.cells.iter().enumerate() {
                let mine = if r == 0 {
                    contract(cell, at(&inherited, s)?, at(&state.angles, s)?, &self.cap)
                        .ok_or("B1: round zero box should be empty")?
                } else {
                    at(&previous, s)?.clone()
                };
                if !box_contains(at(&bounds, s)?, &mine) {
                    return Err(format!("B1/B2: round {r} box of square {s} too small"));
                }
            }
            // Match eager parsed_cut validation even for unreferenced cuts.
            if let Some(cuts) = record.get("cuts") {
                for cut in arr(cuts)? {
                    let fields = arr(cut)?.len();
                    if fields != 4 && fields != 8 {
                        return Err("unsupported cut shape".into());
                    }
                    index(&cut[0])?;
                    rat(&cut[1])?;
                    rat(&cut[2])?;
                    rat(&cut[3])?;
                    if fields == 8 {
                        rat(&cut[4])?;
                        rat(&cut[7])?;
                    }
                }
            }
            let mut cache = RoundCache::default();
            if record.get("closed_pair").is_some() {
                self.check_closed_pair(&state, record, &bounds, counts)?;
                if r + 1 != rounds.len() || node["closed"] != record["closed_pair"][1] {
                    return Err("pair closure not final".into());
                }
                return Ok(());
            }
            if let Some(farkas) = record.get("farkas") {
                let value =
                    self.combination(&state, record, &bounds, farkas, None, (&mut cache, counts))?;
                if value <= 0 {
                    return Err("C3: Farkas combination minimum <= 0".into());
                }
                tick(counts, "closed_lp_ok");
                if r + 1 != rounds.len() || node["closed"] != "lp" {
                    return Err("LP closure not final".into());
                }
                return Ok(());
            }
            match self.check_bounds(&state, node, record, &bounds, &mut cache, counts)? {
                Some(next) => previous = next,
                None => return Ok(()),
            }
        }
        if !node["closed"].is_null() && node["closed"] != "angle" {
            return Err("closed node without closing record".into());
        }
        self.check_open(&state, node, &previous, counts)
    }
    /// Check every round and preserve counters even when a later check fails.
    pub(crate) fn check_node(&self, node: &Value, parent: Option<&Value>) -> (Counts, Result<()>) {
        let mut counts = Counts::new();
        let result = self
            .check_node_inner(node, parent, &mut counts)
            .map_err(|error| format!("node {}: {error}", node["id"]));
        (counts, result)
    }
}

#[cfg(test)]
mod tests {
    use super::{NodeVerifier, Q};
    use serde_json::json;

    #[test]
    fn disc_closure_is_strict_at_unit_distance() {
        let cell = vec![
            [Q::from(0), Q::from(0)],
            [Q::from(2), Q::from(0)],
            [Q::from(2), Q::from(2)],
            [Q::from(0), Q::from(2)],
        ];
        for (xhi, ylo, yhi, accepted) in [
            (Q::from(1), Q::from((1, 2)), Q::from(1), true),
            (Q::from((3, 2)), Q::from(1), Q::from(1), false),
        ] {
            let bounds = [Q::from((1, 2)), xhi, ylo, yhi];
            let verifier = NodeVerifier {
                v3: false,
                trig_keys: std::collections::BTreeSet::default(),
                cells: vec![cell.clone(), cell.clone()],
                cap: Q::from(2),
                pairs: vec![(0, 1)],
                root_angles: vec![[Q::from(0), Q::from(2)]; 2],
                root_boxes: vec![bounds.clone(); 2],
            };
            let strings: Vec<String> = bounds
                .iter()
                .map(|q| format!("{}/{}", q.numer(), q.denom()))
                .collect();
            let node = json!({
                "id": 0, "angles": [["0/1", "2/1"], ["0/1", "2/1"]],
                "windows": [], "closed": "disc",
                "rounds": [{"boxes": [strings, strings], "closed_pair": [0, "disc"]}]
            });
            let (counts, result) = verifier.check_node(&node, None);
            assert_eq!(result.is_ok(), accepted, "{result:?}");
            if accepted {
                for (field, metadata) in [
                    ("final", json!([["invalid", "1/1", "1/2", "1/1"]])),
                    ("taylor", json!({"centres": ["invalid", "0/1"]})),
                    ("taylor", json!({"centres": ["0/1"]})),
                    ("taylor", json!({"centres": ["0/1", "0/1", "0/1"]})),
                    ("taylor", json!(null)),
                ] {
                    let mut malformed = node.clone();
                    malformed[field] = metadata;
                    let (failed_counts, outcome) = verifier.check_node(&malformed, None);
                    assert!(outcome.is_err(), "malformed {field} was accepted");
                    assert!(failed_counts.is_empty());
                }
                let mut annotated = node.clone();
                annotated["taylor"] = json!({"centres": ["0/1", "0/1"]});
                annotated["final"] = json!([strings, strings]);
                assert!(verifier.check_node(&annotated, None).1.is_ok());
            }
            assert_eq!(
                counts.get("closed_disc_ok").copied().unwrap_or(0),
                u64::from(accepted)
            );
        }
    }
}

#[cfg(test)]
mod v3_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn bounds_without_next_use_updated_boxes_only_in_v3() {
        let cell = vec![
            [Q::from(0), Q::from(0)],
            [Q::from(2), Q::from(0)],
            [Q::from(2), Q::from(2)],
            [Q::from(0), Q::from(2)],
        ];
        let bounds = [Q::from(0), Q::from(2), Q::from(0), Q::from(2)];
        // The cell row -x <= 0 proves x >= 0, even when the recorded box is wider.
        let input = [Q::from(-1), Q::from(2), Q::from(0), Q::from(2)];
        let record = json!({"bounds":[[0,1,"0/1",[[["c",0,3],"1/2"]]] ]});
        let state = NodeState {
            angles: vec![[Q::from(0), Q::from(2)]],
            windows: HashMap::new(),
        };
        for v3 in [false, true] {
            let verifier = NodeVerifier {
                v3,
                trig_keys: std::collections::BTreeSet::new(),
                cells: vec![cell.clone()],
                cap: Q::from(3),
                pairs: vec![],
                root_angles: state.angles.clone(),
                root_boxes: vec![input.clone()],
            };
            let mut counts = Counts::new();
            let result = verifier
                .check_bounds(
                    &state,
                    &json!({"closed":null}),
                    &record,
                    std::slice::from_ref(&input),
                    &mut RoundCache::default(),
                    &mut counts,
                )
                .expect("valid bound")
                .expect("nonempty");
            assert_eq!(
                result,
                vec![if v3 { bounds.clone() } else { input.clone() }]
            );
            assert_eq!(counts["bound_ok"], 1);
        }
    }
}
