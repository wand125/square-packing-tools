//! Exact replay of the locally specified v3 angle eliminations.
use crate::exact::{Box4, Q, Span, cos_sin, gap_lower, h_lower, half_pi_multiple, sqrt_upper};
use crate::nodes::{Counts, NodeState, NodeVerifier, Result, arr, at, index, qs, tick};
use serde_json::Value;

#[derive(Clone, Debug, PartialEq)]
struct Component {
    lo: Q,
    hi: Q,
    left: bool,
    right: bool,
}
impl Component {
    fn closed([lo, hi]: &Span) -> Self {
        Self {
            lo: lo.clone(),
            hi: hi.clone(),
            left: true,
            right: true,
        }
    }
    fn nonempty(&self) -> bool {
        self.lo < self.hi || (self.lo == self.hi && self.left && self.right)
    }
}
fn subtract(alive: &[Component], [lo, hi]: &Span) -> Vec<Component> {
    let mut result = Vec::new();
    for c in alive {
        if hi < &c.lo || lo > &c.hi {
            result.push(c.clone());
            continue;
        }
        if &c.lo < lo {
            let part = Component {
                hi: c.hi.clone().min(lo.clone()),
                right: c.hi < *lo && c.right,
                ..c.clone()
            };
            if part.nonempty() {
                result.push(part);
            }
        }
        if hi < &c.hi {
            let part = Component {
                lo: c.lo.clone().max(hi.clone()),
                left: c.lo > *hi && c.left,
                ..c.clone()
            };
            if part.nonempty() {
                result.push(part);
            }
        }
    }
    result
}
fn covered(alive: &[Component], spans: &[Span]) -> bool {
    spans
        .iter()
        .fold(alive.to_vec(), |a, b| subtract(&a, b))
        .is_empty()
}
fn rotated(t: &Q, k: usize) -> [Q; 4] {
    let [cl, ch, sl, sh] = cos_sin(t);
    match k {
        0 => [cl, ch, sl, sh],
        1 => [-sh, -sl, cl, ch],
        2 => [-ch, -cl, -sh, -sl],
        _ => [sl, sh, -ch, -cl],
    }
}
fn linear_upper([cl, ch, sl, sh]: &[Q; 4], x: &Q, y: &Q) -> Q {
    (cl.clone() * x).max(ch.clone() * x) + (sl.clone() * y).max(sh.clone() * y)
}
fn family_meets([a, b]: &Span, k: i32, window: Option<&Span>) -> bool {
    let Some([wl, wh]) = window else {
        return true;
    };
    let shift = half_pi_multiple(k);
    let low = a.clone() + &shift[0];
    let high = b.clone() + &shift[1];
    let period = half_pi_multiple(4);
    let ratios = [wl.clone() - &high, wh.clone() - &low]
        .into_iter()
        .flat_map(|n| period.iter().map(move |d| n.clone() / d))
        .collect::<Vec<_>>();
    let start = ratios
        .iter()
        .min()
        .expect("four ratios")
        .clone()
        .ceil()
        .numer()
        .clone();
    let stop = ratios
        .iter()
        .max()
        .expect("four ratios")
        .clone()
        .floor()
        .numer()
        .clone();
    if stop.clone() - &start > 16 {
        return true;
    }
    let mut turn = start;
    while turn <= stop {
        // Arbitrary-size turns retain the reference's exact modulo behaviour.
        let (d0, d1) = if turn >= 0 {
            (&period[0], &period[1])
        } else {
            (&period[1], &period[0])
        };
        if low.clone() + d0.clone() * &turn <= *wh && *wl <= high.clone() + d1.clone() * &turn {
            return true;
        }
        turn += 1;
    }
    false
}
fn always_overlapping(
    state: &NodeState,
    boxes: &[Box4],
    pair: (usize, usize),
    p: usize,
    first: &Span,
    second: &Span,
) -> bool {
    let (i, j) = pair;
    let dx = [
        boxes[j][0].clone() - &boxes[i][1],
        boxes[j][1].clone() - &boxes[i][0],
    ];
    let dy = [
        boxes[j][2].clone() - &boxes[i][3],
        boxes[j][3].clone() - &boxes[i][2],
    ];
    let gap = gap_lower(&first[0], &first[1], &second[0], &second[1]);
    let window = state.windows.get(&p);
    for span in [first, second] {
        for k in 0..4 {
            if !family_meets(span, i32::try_from(k).expect("quarter turn"), window) {
                continue;
            }
            let na = rotated(&span[0], k);
            let nb = rotated(&span[1], k);
            for x in &dx {
                for y in &dy {
                    let no_interior = span[1].clone() - &span[0] < half_pi_multiple(2)[0]
                        && (linear_upper(&na, y, &-x.clone()) < 0
                            || linear_upper(&nb, &-y.clone(), x) < 0);
                    let upper = if no_interior {
                        linear_upper(&na, x, y).max(linear_upper(&nb, x, y))
                    } else {
                        sqrt_upper(&(x.clone() * x + y.clone() * y))
                    };
                    if upper >= gap {
                        return false;
                    }
                }
            }
        }
    }
    if let Some(window) = window {
        for w in window {
            let support = h_lower(&(w.clone() - &first[1]), &(w.clone() - &first[0]))
                + h_lower(&(w.clone() - &second[1]), &(w.clone() - &second[0]));
            let normal = rotated(w, 0);
            if dx
                .iter()
                .any(|x| dy.iter().any(|y| linear_upper(&normal, x, y) >= support))
            {
                return false;
            }
        }
    }
    true
}

pub(crate) fn target(node: &Value) -> Result<Vec<Span>> {
    let split = node["split"]
        .as_object()
        .ok_or("T2: invalid tighten split")?;
    let value = arr(&split["tighten"])?;
    if split.len() != 1 || value.len() != 2 {
        return Err("T2: invalid tighten split".into());
    }
    let old = arr(&node["angles"])?;
    let new = arr(&value[1])?;
    if old.len() != new.len() {
        return Err("T2: wrong tighten angle count".into());
    }
    old.iter()
        .zip(new)
        .map(|(old, new)| {
            let [lo, hi] = qs::<2>(old)?;
            let span = qs::<2>(new)?;
            if !(lo <= span[0] && span[0] <= span[1] && span[1] <= hi) {
                return Err("T2: tighten target outside parent".into());
            }
            Ok(span)
        })
        .collect()
}
impl NodeVerifier {
    fn elimination_span(&self, value: &Value) -> Result<Span> {
        let values = arr(value).map_err(|_| "E: invalid elimination interval")?;
        if values.len() != 2 {
            return Err("E: invalid elimination interval".into());
        }
        if !values
            .iter()
            .all(|v| v.as_str().is_some_and(|s| self.trig_keys.contains(s)))
        {
            return Err("E: elimination angle missing from trig table".into());
        }
        let span = qs::<2>(value)?;
        if span[0] > span[1] {
            return Err("E: reversed elimination interval".into());
        }
        Ok(span)
    }
    pub(crate) fn check_eliminations(
        &self,
        state: &NodeState,
        node: &Value,
        boxes: &[Box4],
        counts: &mut Counts,
    ) -> Result<()> {
        let closing = node["closed"] == "angle";
        let eliminations = if closing {
            &node["angle"]
        } else {
            &node["split"]["tighten"][0]
        };
        let mut alive: Vec<_> = state
            .angles
            .iter()
            .map(|s| vec![Component::closed(s)])
            .collect();
        for e in arr(eliminations).map_err(|_| "E: eliminations must be a list")? {
            let e = arr(e).map_err(|_| "E: invalid elimination record")?;
            if e.len() != 4 && e.len() != 6 {
                return Err("E: invalid elimination record".into());
            }
            let s = index(&e[0])
                .ok()
                .filter(|&s| s < alive.len())
                .ok_or("E: invalid eliminated square")?;
            let span = self.elimination_span(&Value::Array(e[1..3].to_vec()))?;
            let after = subtract(&alive[s], &span);
            if after == alive[s] {
                return Err("E: elimination does not meet alive set".into());
            }
            if e.len() == 4 {
                if e[3] != "wall" {
                    return Err("E: unknown elimination kind".into());
                }
                let h = h_lower(&span[0], &span[1]);
                let upper = self.cap.clone() - &h;
                let [xl, xh, yl, yh] = at(boxes, s)?;
                if !(h > upper || xh < &h || xl > &upper || yh < &h || yl > &upper) {
                    return Err("E: wall elimination not proved".into());
                }
                tick(counts, "wall_elimination_ok");
            } else {
                let j = index(&e[3])
                    .ok()
                    .filter(|&j| j < alive.len() && j != s)
                    .ok_or("E: invalid partner square")?;
                let p = index(&e[4])
                    .ok()
                    .filter(|&p| {
                        self.pairs
                            .get(p)
                            .is_some_and(|&pair| pair == (s, j) || pair == (j, s))
                    })
                    .ok_or("E: invalid elimination pair")?;
                let partners = arr(&e[5])
                    .map_err(|_| "E: invalid partner intervals")?
                    .iter()
                    .map(|b| self.elimination_span(b))
                    .collect::<Result<Vec<_>>>()?;
                if !covered(&alive[j], &partners) {
                    return Err("E: partner intervals do not cover alive set".into());
                }
                for b in &partners {
                    let (first, second) = if self.pairs[p].0 == s {
                        (&span, b)
                    } else {
                        (b, &span)
                    };
                    if !always_overlapping(state, boxes, self.pairs[p], p, first, second) {
                        return Err("E: pair elimination not always overlapping".into());
                    }
                }
                tick(counts, "pair_elimination_ok");
            }
            alive[s] = after;
        }
        if closing {
            if !alive.iter().any(Vec::is_empty) {
                return Err("E: angle closure has no empty alive set".into());
            }
            tick(counts, "closed_angle_ok");
        } else {
            if !alive
                .iter()
                .zip(target(node)?)
                .all(|(a, b)| covered(a, &[b]))
            {
                return Err("E: tighten target does not contain alive set".into());
            }
            tick(counts, "tighten_split_ok");
            tick(counts, "open_ok");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn subtraction_owns_endpoints_and_detects_singletons() {
        let full = vec![Component::closed(&[Q::from(0), Q::from(2)])];
        let hole = subtract(&full, &[Q::from(1), Q::from(1)]);
        assert_eq!(hole.len(), 2);
        assert!(!hole[0].right && !hole[1].left);
        assert_eq!(subtract(&hole, &[Q::from(1), Q::from(1)]), hole);
        let right = subtract(&full, &[Q::from(0), Q::from(1)]);
        assert!(!right[0].left && right[0].right);
        assert!(covered(&right, &[[Q::from(1), Q::from(2)]]));
        assert!(!covered(&full, &[[Q::from(0), Q::from(1)]]));
        let singleton = vec![Component::closed(&[Q::from(1), Q::from(1)])];
        assert!(subtract(&singleton, &[Q::from(1), Q::from(2)]).is_empty());
    }

    #[test]
    fn families_wrap_negative_turns_and_keep_uncertain_boundaries() {
        let span = [Q::from(0), Q::from((1, 10))];
        assert!(family_meets(&span, 0, None));
        assert!(!family_meets(&span, 0, Some(&[Q::from(1), Q::from(2)])));
        assert!(family_meets(&span, 0, Some(&[Q::from(-7), Q::from(-6)])));
        assert!(family_meets(&span, 1, Some(&half_pi_multiple(1))));
        assert!(family_meets(
            &span,
            0,
            Some(&[Q::from(-1000), Q::from(1000)])
        ));
    }

    #[test]
    fn wall_elimination_replays_against_final_boxes() {
        let span = [Q::from((1, 2)), Q::from(1)];
        let state = NodeState {
            angles: vec![span],
            windows: std::collections::HashMap::new(),
        };
        let verifier = NodeVerifier {
            v3: true,
            trig_keys: ["1/2".to_owned(), "1/1".to_owned()].into_iter().collect(),
            cells: vec![],
            cap: Q::from(3),
            pairs: vec![],
            root_angles: vec![],
            root_boxes: vec![],
        };
        let node = serde_json::json!({"closed":"angle","angle":[[0,"1/2","1/1","wall"]]});
        let mut counts = Counts::new();
        let boxes = [[Q::from((1, 2)), Q::from((1, 2)), Q::from(1), Q::from(1)]];
        verifier
            .check_eliminations(&state, &node, &boxes, &mut counts)
            .expect("wall excludes angle span");
        assert_eq!(counts["wall_elimination_ok"], 1);
        assert_eq!(counts["closed_angle_ok"], 1);
    }

    #[test]
    fn fixed_window_ends_are_mandatory_and_overlap_is_strict() {
        let angles = [Q::from(0), Q::from(0)];
        let mut state = NodeState {
            angles: vec![angles.clone(); 2],
            windows: std::collections::HashMap::new(),
        };
        let first = [Q::from(0), Q::from(0), Q::from(0), Q::from(0)];
        let touching = [Q::from(1), Q::from(1), Q::from(0), Q::from(0)];
        assert!(!always_overlapping(
            &state,
            &[first.clone(), touching],
            (0, 1),
            0,
            &angles,
            &angles
        ));
        // No edge family meets [0.7,0.8], but its fixed directions separate these boxes.
        state
            .windows
            .insert(0, [Q::from((7, 10)), Q::from((8, 10))]);
        let distant = [Q::from(2), Q::from(2), Q::from(2), Q::from(2)];
        assert!(!always_overlapping(
            &state,
            &[first.clone(), distant],
            (0, 1),
            0,
            &angles,
            &angles
        ));
        assert!(always_overlapping(
            &state,
            &[first.clone(), first],
            (0, 1),
            0,
            &angles,
            &angles
        ));
    }
}
