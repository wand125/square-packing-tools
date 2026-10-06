//! Independent exact arithmetic and geometry translated from the standing verifier.
use rug::{Integer, Rational};
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::OnceLock;

pub(crate) type Q = Rational;
pub(crate) type Point = [Q; 2];
pub(crate) type Box4 = [Q; 4];
pub(crate) type Span = [Q; 2];
pub(crate) type Plane = [Q; 3];

pub(crate) fn parse(text: &str) -> Result<Q, String> {
    let (n, d) = text
        .split_once('/')
        .ok_or_else(|| format!("invalid rational: {text}"))?;
    let n = n.parse::<Integer>().map_err(|e| e.to_string())?;
    let d = d.parse::<Integer>().map_err(|e| e.to_string())?;
    if d == 0 {
        return Err("zero rational denominator".into());
    }
    Ok(Q::from((n, d)))
}

fn floor_ratio(n: &Integer, d: &Integer) -> Integer {
    let mut result = n.clone() / d;
    if n < &0 && n.clone() % d != 0 {
        result -= 1;
    }
    result
}
fn ceil_ratio(n: &Integer, d: &Integer) -> Integer {
    -floor_ratio(&-n.clone(), d)
}
fn arctan_inv(n: u32, terms: u32) -> Span {
    let mut total = Q::new();
    let mut last = Q::new();
    let mut power = Integer::from(n);
    for k in 0..terms {
        last = Q::from((Integer::from(1), power.clone() * (2 * k + 1)));
        if k.is_multiple_of(2) {
            total += &last;
        } else {
            total -= &last;
        }
        power *= n * n;
    }
    if terms.is_multiple_of(2) {
        [total.clone(), total + last]
    } else {
        [total.clone() - last, total]
    }
}
fn pi() -> &'static Span {
    static PI: OnceLock<Span> = OnceLock::new();
    PI.get_or_init(|| {
        let a = arctan_inv(5, 40);
        let b = arctan_inv(239, 20);
        [
            a[0].clone() * 16 - b[1].clone() * 4,
            a[1].clone() * 16 - b[0].clone() * 4,
        ]
    })
}
pub(crate) fn constants_hold() -> bool {
    let p = pi();
    let denominator = Integer::from(10).pow(40);
    let below = Q::from((
        Integer::from_str_radix("314159265358979323846", 10).expect("constant"),
        Integer::from(10).pow(20),
    ));
    let above = Q::from((
        Integer::from_str_radix("314159265358979323847", 10).expect("constant"),
        Integer::from(10).pow(20),
    ));
    p[1].clone() - &p[0] < Q::from((1, denominator)) && below < p[0] && p[0] < p[1] && p[1] < above
}
pub(crate) fn half_pi_multiple(k: i32) -> Span {
    let p = pi();
    if k >= 0 {
        [p[0].clone() * k / 2, p[1].clone() * k / 2]
    } else {
        [p[1].clone() * k / 2, p[0].clone() * k / 2]
    }
}
thread_local! { static TRIG: RefCell<BTreeMap<Q, [Q; 4]>> = const { RefCell::new(BTreeMap::new()) }; }
pub(crate) fn cos_sin(t: &Q) -> [Q; 4] {
    TRIG.with(|cache| {
        if let Some(value) = cache.borrow().get(t) {
            return value.clone();
        }
        let result = cos_sin_bits(t, 160);
        cache.borrow_mut().insert(t.clone(), result.clone());
        result
    })
}
pub(crate) fn cos_sin_bits(t: &Q, bits: u32) -> [Q; 4] {
    let scale = Integer::from(1) << bits;
    let mut c_lo = Integer::new();
    let mut c_hi = Integer::new();
    let mut s_lo = Integer::new();
    let mut s_hi = Integer::new();
    let mut power_num = Integer::from(1);
    let mut power_den = Integer::from(1);
    let mut fact = Integer::from(1);
    let mut n = 0u32;
    let tail = loop {
        let value_num = power_num.clone() * &scale;
        let value_den = power_den.clone() * &fact;
        let lo = floor_ratio(&value_num, &value_den);
        let hi = ceil_ratio(&value_num, &value_den);
        match n % 4 {
            0 => {
                c_lo += lo;
                c_hi += hi;
            }
            1 => {
                s_lo += lo;
                s_hi += hi;
            }
            2 => {
                c_lo -= hi;
                c_hi -= lo;
            }
            _ => {
                s_lo -= hi;
                s_hi -= lo;
            }
        }
        n += 1;
        power_num *= t.numer();
        power_den *= t.denom();
        fact *= n;
        let tail = ceil_ratio(
            &(power_num.clone().abs() * &scale),
            &(power_den.clone() * &fact),
        ) + 1;
        if tail <= 2 && n > 2 {
            break tail;
        }
    };
    [
        Q::from((c_lo - &tail, scale.clone())),
        Q::from((c_hi + &tail, scale.clone())),
        Q::from((s_lo - &tail, scale.clone())),
        Q::from((s_hi + &tail, scale)),
    ]
}
fn least_abs(lo: &Q, hi: &Q) -> Q {
    if lo >= &0 {
        lo.clone()
    } else if hi <= &0 {
        -hi.clone()
    } else {
        Q::new()
    }
}
fn h_at(t: &Q) -> Q {
    let [cl, ch, sl, sh] = cos_sin(t);
    (least_abs(&cl, &ch) + least_abs(&sl, &sh)) / 2
}
// Dividing by the positive Machin interval gives an enclosure of all possible
// half-pi multiples. Testing integer existence avoids the oracle's floating
// candidate-index estimate while preserving its conservative overlap test.
fn meets_multiple(lo: &Q, hi: &Q) -> bool {
    let [hp_lo, hp_hi] = half_pi_multiple(1);
    if hi.clone() - lo >= hp_lo {
        return true;
    }
    let lower = lo.clone() / if lo >= &0 { &hp_hi } else { &hp_lo };
    let upper = hi.clone() / if hi >= &0 { &hp_lo } else { &hp_hi };
    ceil_ratio(lower.numer(), lower.denom()) <= floor_ratio(upper.numer(), upper.denom())
}
pub(crate) fn h_lower(lo: &Q, hi: &Q) -> Q {
    let half = Q::from((1, 2));
    if meets_multiple(lo, hi) {
        half
    } else {
        half.max(h_at(lo).min(h_at(hi)))
    }
}
pub(crate) fn gap_lower(ai: &Q, bi: &Q, aj: &Q, bj: &Q) -> Q {
    if aj <= bi && ai <= bj {
        return Q::from(1);
    }
    let lo = aj.clone() - bi;
    let hi = bj.clone() - ai;
    if meets_multiple(&lo, &hi) {
        Q::from(1)
    } else {
        Q::from(1).max(Q::from((1, 2)) + h_at(&lo).min(h_at(&hi)))
    }
}
pub(crate) fn sqrt_upper(value: &Q) -> Q {
    if value <= &0 {
        return Q::new();
    }
    let scale = Integer::from(10).pow(30);
    let scaled = value.clone() * &scale * &scale;
    let root = floor_ratio(scaled.numer(), scaled.denom()).sqrt() + 1;
    Q::from((root, scale))
}
pub(crate) fn clip_polygon(polygon: &[Point], a: &Q, b: &Q, c: &Q) -> Vec<Point> {
    let mut result = Vec::new();
    for (index, start) in polygon.iter().enumerate() {
        let end = &polygon[(index + 1) % polygon.len()];
        let fs = a.clone() * &start[0] + b.clone() * &start[1] - c;
        let fe = a.clone() * &end[0] + b.clone() * &end[1] - c;
        if fs <= 0 {
            result.push(start.clone());
        }
        if fs.clone() * &fe < 0 {
            let t = fs.clone() / (fs - fe);
            result.push([
                start[0].clone() + t.clone() * (end[0].clone() - &start[0]),
                start[1].clone() + t * (end[1].clone() - &start[1]),
            ]);
        }
    }
    result
}
pub(crate) fn clip_cell_to_box(cell: &[Point], bounds: &Box4) -> Option<Box4> {
    if bounds[0] > bounds[1] || bounds[2] > bounds[3] {
        return None;
    }
    let mut current = cell.to_vec();
    for [a, y, c] in [
        [Q::from(-1), Q::new(), -bounds[0].clone()],
        [Q::from(1), Q::new(), bounds[1].clone()],
        [Q::new(), Q::from(-1), -bounds[2].clone()],
        [Q::new(), Q::from(1), bounds[3].clone()],
    ] {
        current = clip_polygon(&current, &a, &y, &c);
        if current.is_empty() {
            return None;
        }
    }
    Some([
        bounds[0]
            .clone()
            .max(current.iter().map(|p| p[0].clone()).min()?),
        bounds[1]
            .clone()
            .min(current.iter().map(|p| p[0].clone()).max()?),
        bounds[2]
            .clone()
            .max(current.iter().map(|p| p[1].clone()).min()?),
        bounds[3]
            .clone()
            .min(current.iter().map(|p| p[1].clone()).max()?),
    ])
}
pub(crate) fn box_contains(outer: &Box4, inner: &Box4) -> bool {
    outer[0] <= inner[0] && inner[1] <= outer[1] && outer[2] <= inner[2] && inner[3] <= outer[3]
}
pub(crate) fn contract(cell: &[Point], b: &Box4, angle: &Span, cap: &Q) -> Option<Box4> {
    let h = h_lower(&angle[0], &angle[1]);
    clip_cell_to_box(
        cell,
        &[
            b[0].clone().max(h.clone()),
            b[1].clone().min(cap.clone() - &h),
            b[2].clone().max(h.clone()),
            b[3].clone().min(cap.clone() - h),
        ],
    )
}
pub(crate) fn box_max_linear(nx: &Q, ny: &Q, dx: &Span, dy: &Span) -> Q {
    nx.clone() * &dx[usize::from(nx >= &0)] + ny.clone() * &dy[usize::from(ny >= &0)]
}
pub(crate) fn interval_mul(a: &Span, b: &Span) -> Span {
    let values = [
        a[0].clone() * &b[0],
        a[0].clone() * &b[1],
        a[1].clone() * &b[0],
        a[1].clone() * &b[1],
    ];
    let mut lo = values[0].clone();
    let mut hi = lo.clone();
    for v in values {
        lo = lo.min(v.clone());
        hi = hi.max(v);
    }
    [lo, hi]
}
pub(crate) fn enclosed_max(c: &Span, s: &Span, dx: &Span, dy: &Span) -> Q {
    interval_mul(c, dx)[1].clone() + &interval_mul(s, dy)[1]
}
pub(crate) fn plane_box_min(u: &Point, plane: &Plane, dx: &Span, dy: &Span) -> Option<Q> {
    let polygon = [
        [dx[0].clone(), dy[0].clone()],
        [dx[1].clone(), dy[0].clone()],
        [dx[1].clone(), dy[1].clone()],
        [dx[0].clone(), dy[1].clone()],
    ];
    clip_polygon(
        &polygon,
        &-plane[0].clone(),
        &-plane[1].clone(),
        &-plane[2].clone(),
    )
    .iter()
    .map(|p| u[0].clone() * &p[0] + u[1].clone() * &p[1])
    .min()
}
fn cross(o: &Point, a: &Point, b: &Point) -> Q {
    (a[0].clone() - &o[0]) * (b[1].clone() - &o[1])
        - (a[1].clone() - &o[1]) * (b[0].clone() - &o[0])
}
pub(crate) fn hull_vertices(points: &[Point]) -> BTreeSet<Point> {
    let pts: BTreeSet<_> = points.iter().cloned().collect();
    if pts.len() <= 2 {
        return pts;
    }
    let mut lower: Vec<Point> = Vec::new();
    let mut upper: Vec<Point> = Vec::new();
    for p in &pts {
        while lower.len() >= 2 && cross(&lower[lower.len() - 2], &lower[lower.len() - 1], p) <= 0 {
            lower.pop();
        }
        lower.push(p.clone());
    }
    for p in pts.iter().rev() {
        while upper.len() >= 2 && cross(&upper[upper.len() - 2], &upper[upper.len() - 1], p) <= 0 {
            upper.pop();
        }
        upper.push(p.clone());
    }
    lower.pop();
    upper.pop();
    lower.extend(upper);
    lower.into_iter().collect()
}

use rug::ops::Pow;

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn machin_constants_and_signed_rounding() {
        assert!(constants_hold());
        assert_eq!(floor_ratio(&Integer::from(-5), &Integer::from(2)), -3);
        assert_eq!(ceil_ratio(&Integer::from(-5), &Integer::from(2)), -2);
        assert!(parse("1/0").is_err());
    }
    #[test]
    fn exact_zero_trig_and_gap() {
        let scale: Integer = Integer::from(1) << 160;
        let got = cos_sin(&Q::new());
        assert_eq!(
            got,
            [
                Q::from((scale.clone() - 1, scale.clone())),
                Q::from((scale.clone() + 1, scale.clone())),
                Q::from((-1, scale.clone())),
                Q::from((1, scale))
            ]
        );
        assert_eq!(h_lower(&Q::new(), &Q::from(1)), Q::from((1, 2)));
        assert_eq!(gap_lower(&Q::new(), &Q::from(1), &Q::new(), &Q::from(1)), 1);
    }
    #[test]
    fn clipping_and_degenerate_hull() {
        let points = [
            [Q::new(), Q::new()],
            [Q::from(2), Q::new()],
            [Q::new(), Q::from(2)],
        ];
        let b = [Q::new(), Q::from(1), Q::new(), Q::from(1)];
        assert_eq!(clip_cell_to_box(&points, &b), Some(b));
        let points = [
            [Q::new(), Q::new()],
            [Q::from(1), Q::from(1)],
            [Q::from(2), Q::from(2)],
        ];
        assert_eq!(hull_vertices(&points).len(), 2);
    }
}

pub(crate) fn hp_lo() -> Q {
    half_pi_multiple(1)[0].clone()
}
pub(crate) fn most_abs(lo: &Q, hi: &Q) -> Q {
    (-lo.clone()).max(hi.clone())
}

#[cfg(test)]
mod oracle_tests {
    use super::*;
    /// Fixtures evaluated by the standing Python verifier, including a negative angle.
    #[test]
    fn fixed_point_matches_standing_verifier() {
        let fixtures = [
            (
                "1/3",
                160,
                [
                    "10789500970673431444073618108781366501422822637/11417981541647679048466287755595961091061972992",
                    "1381056124246199224841423117924014912182121297555/1461501637330902918203684832716283019655932542976",
                    "3735903008543475313681114986208456000222116237/11417981541647679048466287755595961091061972992",
                    "478195585093564840151182718234682368028430878355/1461501637330902918203684832716283019655932542976",
                ],
            ),
            (
                "-7/5",
                160,
                [
                    "124203628820578841533613103813454385287236624795/730750818665451459101842416358141509827966271488",
                    "15525453602572355191701637976681798160904578101/91343852333181432387730302044767688728495783936",
                    "-1440236393885430736539352579995030111823143340559/1461501637330902918203684832716283019655932542976",
                    "-1440236393885430736539352579995030111823143340533/1461501637330902918203684832716283019655932542976",
                ],
            ),
            (
                "1/1000",
                64,
                [
                    "18446734850338283373/18446744073709551616",
                    "18446734850338283379/18446744073709551616",
                    "4611685249813089/4611686018427387904",
                    "18446740999252363/18446744073709551616",
                ],
            ),
        ];
        for (angle, bits, expected) in fixtures {
            assert_eq!(
                cos_sin_bits(&parse(angle).expect("fixture"), bits),
                expected.map(|s| parse(s).expect("fixture"))
            );
        }
    }
}

#[cfg(test)]
mod boundary_tests {
    use super::*;
    #[test]
    fn critical_angle_enclosures_and_separated_intervals() {
        for k in -8..=8 {
            let boundary = half_pi_multiple(k);
            assert!(meets_multiple(&boundary[0], &boundary[1]));
            assert_eq!(h_lower(&boundary[0], &boundary[1]), Q::from((1, 2)));
        }
        assert!(!meets_multiple(&Q::from((1, 4)), &Q::from((1, 3))));
        assert!(!meets_multiple(&Q::from((-1, 3)), &Q::from((-1, 4))));
        assert!(h_lower(&Q::from((1, 4)), &Q::from((1, 3))) > Q::from((1, 2)));
    }
    #[test]
    fn square_root_and_empty_plane_intersection() {
        for value in [Q::new(), Q::from((1, 100)), Q::from(2), Q::from(4)] {
            let upper = sqrt_upper(&value);
            assert!(upper.clone() * upper >= value);
        }
        let span = [Q::new(), Q::from(1)];
        let objective = [Q::from(1), Q::from(1)];
        assert_eq!(
            plane_box_min(
                &objective,
                &[Q::from(1), Q::new(), Q::from(2)],
                &span,
                &span
            ),
            None
        );
        assert_eq!(
            plane_box_min(
                &objective,
                &[Q::from(1), Q::new(), Q::from((1, 2))],
                &span,
                &span
            ),
            Some(Q::from((1, 2)))
        );
    }
}
