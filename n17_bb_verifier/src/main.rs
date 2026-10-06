//! Independent exact verification of non-Taylor n17 branch-and-bound certificates.
mod compact;
mod exact;
mod nodes;
mod tighten;

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::BufReader;
use std::path::{Path, PathBuf};
use std::time::Instant;

use flate2::read::MultiGzDecoder;
use rayon::prelude::*;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use exact::{Box4, Point, Q, Span};
use nodes::NodeVerifier;

type Check<T> = Result<T, String>;

fn array(value: &Value) -> Check<&Vec<Value>> {
    value.as_array().ok_or_else(|| "expected array".into())
}
fn text(value: &Value) -> Check<&str> {
    value.as_str().ok_or_else(|| "expected string".into())
}
fn id(value: &Value) -> Check<u64> {
    value
        .as_u64()
        .ok_or_else(|| "expected nonnegative node id".into())
}
fn index(value: &Value) -> Check<usize> {
    usize::try_from(id(value)?).map_err(|e| e.to_string())
}
fn rational(value: &Value) -> Check<Q> {
    exact::parse(text(value)?)
}
fn cell_rational(value: &Value) -> Check<Q> {
    let value = text(value)?;
    if value.contains('/') {
        exact::parse(value)
    } else {
        exact::parse(&format!("{value}/1"))
    }
}
fn cell_point(value: &Value) -> Check<Point> {
    array(value)?
        .iter()
        .map(cell_rational)
        .collect::<Check<Vec<_>>>()?
        .try_into()
        .map_err(|_| "cell point needs two coordinates".into())
}
fn rationals<const N: usize>(value: &Value) -> Check<[Q; N]> {
    array(value)?
        .iter()
        .map(rational)
        .collect::<Check<Vec<_>>>()?
        .try_into()
        .map_err(|_| format!("expected {N} rational values"))
}
fn read_named(directory: &Path, name: &str) -> Check<Value> {
    let path = directory.join(format!("{name}.json.gz"));
    let file = File::open(path).map_err(|e| e.to_string())?;
    serde_json::from_reader(BufReader::new(MultiGzDecoder::new(file))).map_err(|e| e.to_string())
}

#[derive(Default)]
struct Options {
    directory: PathBuf,
    manifest: Option<String>,
    cells: Option<PathBuf>,
    cells_sha256: Option<String>,
    output: Option<PathBuf>,
    node_ids: Option<PathBuf>,
    threads: usize,
}
impl Options {
    fn parse() -> Check<Self> {
        let mut args = std::env::args().skip(1);
        let mut result = Self {
            threads: 1,
            ..Self::default()
        };
        while let Some(arg) = args.next() {
            if arg == "--help" || arg == "-h" {
                println!(
                    "n17bb-verify DIRECTORY [--manifest NAME] [--cells JSON --cells-sha256 SHA256] [--threads N] [--node-ids JSON] [--output JSON]\nDefault cells: independently exported cover bundled with the verifier. --node-ids is a planning sample, never a full verdict."
                );
                std::process::exit(0);
            }
            match arg.as_str() {
                "--manifest" => result.manifest = Some(args.next().ok_or("missing manifest")?),
                "--cells" => result.cells = Some(args.next().ok_or("missing cells")?.into()),
                "--cells-sha256" => {
                    result.cells_sha256 = Some(args.next().ok_or("missing digest")?);
                }
                "--output" => result.output = Some(args.next().ok_or("missing output")?.into()),
                "--node-ids" => {
                    result.node_ids = Some(args.next().ok_or("missing node ids")?.into());
                }
                "--threads" => {
                    result.threads = args
                        .next()
                        .ok_or("missing threads")?
                        .parse()
                        .map_err(|e: std::num::ParseIntError| e.to_string())?;
                }
                _ if !arg.starts_with('-') && result.directory.as_os_str().is_empty() => {
                    result.directory = arg.into();
                }
                _ => return Err(format!("unknown argument {arg}")),
            }
        }
        if result.directory.as_os_str().is_empty() || result.threads == 0 {
            return Err("directory and positive --threads required".into());
        }
        if result.cells.is_some() != result.cells_sha256.is_some() {
            return Err("--cells requires --cells-sha256".into());
        }
        Ok(result)
    }
}

fn load_cells(options: &Options) -> Check<Value> {
    if let Some(path) = &options.cells {
        let bytes = fs::read(path).map_err(|e| e.to_string())?;
        let digest = format!("{:x}", Sha256::digest(&bytes));
        if options.cells_sha256.as_ref() != Some(&digest) {
            return Err(format!("cells file digest {digest} is not the stated one"));
        }
        serde_json::from_slice(&bytes).map_err(|e| e.to_string())
    } else {
        serde_json::from_str(include_str!("../tests/cells.json")).map_err(|e| e.to_string())
    }
}

fn build_verifier(manifest: &Value) -> Check<NodeVerifier> {
    let header = &manifest["header"];
    Ok(NodeVerifier {
        v3: manifest["schema"] == "n17-subpattern-bb-certificate/v3",
        trig_keys: BTreeSet::new(),
        cap: rational(&header["cap"])?,
        cells: array(&header["cells"])?
            .iter()
            .map(|cell| array(cell)?.iter().map(rationals::<2>).collect())
            .collect::<Check<_>>()?,
        pairs: array(&header["pairs"])?
            .iter()
            .map(|pair| {
                let p = array(pair)?;
                if p.len() != 2 {
                    return Err("pair needs two indices".into());
                }
                Ok((index(&p[0])?, index(&p[1])?))
            })
            .collect::<Check<_>>()?,
        root_angles: array(&header["root_angles"])?
            .iter()
            .map(rationals::<2>)
            .collect::<Check<Vec<Span>>>()?,
        root_boxes: array(&header["root_boxes"])?
            .iter()
            .map(rationals::<4>)
            .collect::<Check<Vec<Box4>>>()?,
    })
}

fn json_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
        Value::Number(value) => value
            .to_string()
            .split(['e', 'E'])
            .next()
            .is_some_and(|mantissa| mantissa.chars().any(|ch| matches!(ch, '1'..='9'))),
    }
}

fn check_header(
    manifest: &Value,
    verifier: &NodeVerifier,
    cells: &Value,
    failures: &mut Vec<String>,
) -> Check<()> {
    let h = &manifest["header"];
    if let Some(settings) = h.get("settings") {
        let settings = settings
            .as_object()
            .ok_or("header settings must be an object")?;
        if settings.get("taylor").is_some_and(json_truthy) {
            return Err("schema: Taylor certificates are not supported".into());
        }
    }
    if manifest["schema"] != "n17-subpattern-bb-certificate/v1" && !verifier.v3 {
        return Err("schema: only non-Taylor interval schemas v1 and v3 supported".into());
    }
    // Cell exports accept the Fraction string form, including integers.
    if verifier.cap != cell_rational(&cells["U"])? {
        failures.push("header cap is not the cells' cap".into());
    }
    let pattern = array(&h["pattern"])?;
    let cell_order = array(&cells["order"])?;
    if pattern.len() != verifier.cells.len()
        || verifier.root_boxes.len() != pattern.len()
        || verifier.root_angles.len() != pattern.len()
    {
        return Err("header cell, pattern, box or angle dimensions differ".into());
    }
    for (name, polygon) in pattern.iter().zip(&verifier.cells) {
        let name = text(name)?;
        if !cell_order.iter().any(|entry| entry.as_str() == Some(name)) {
            failures.push(format!("header cell {name} is not in the cells' source"));
            continue;
        }
        let source: Vec<Point> = array(&cells["cells"][name])?
            .iter()
            .map(cell_point)
            .collect::<Check<_>>()?;
        if exact::hull_vertices(&source) != polygon.iter().cloned().collect() {
            failures.push(format!("header cell {name} differs from the cells' source"));
        }
        if polygon.len() < 3 {
            return Err(format!("header cell {name} has fewer than three vertices"));
        }
        for e in 0..polygon.len() {
            let o = &polygon[e];
            let a = &polygon[(e + 1) % polygon.len()];
            let b = &polygon[(e + 2) % polygon.len()];
            let cross = (a[0].clone() - &o[0]) * (b[1].clone() - &o[1])
                - (a[1].clone() - &o[1]) * (b[0].clone() - &o[0]);
            if cross <= 0 {
                failures.push(format!(
                    "header cell {name} is not strictly counterclockwise"
                ));
            }
        }
    }
    let expected: Vec<_> = (0..verifier.cells.len())
        .flat_map(|i| (i + 1..verifier.cells.len()).map(move |j| (i, j)))
        .collect();
    if verifier.pairs != expected {
        failures.push("header pairs are not all pairs".into());
    }
    for [lo, hi] in &verifier.root_angles {
        if hi.clone() - lo <= exact::half_pi_multiple(1)[1] {
            failures.push("root angle interval narrower than pi/2".into());
        }
    }
    for (cell, bounds) in verifier.cells.iter().zip(&verifier.root_boxes) {
        let mut extent = [
            cell[0][0].clone(),
            cell[0][0].clone(),
            cell[0][1].clone(),
            cell[0][1].clone(),
        ];
        for p in cell {
            extent[0] = extent[0].clone().min(p[0].clone());
            extent[1] = extent[1].clone().max(p[0].clone());
            extent[2] = extent[2].clone().min(p[1].clone());
            extent[3] = extent[3].clone().max(p[1].clone());
        }
        if !exact::box_contains(bounds, &extent) {
            failures.push("root box misses its cell".into());
        }
    }
    for (key, value) in h["half_pi_multiples"]
        .as_object()
        .ok_or("half_pi_multiples must be object")?
    {
        let k: i32 = key
            .parse()
            .map_err(|e: std::num::ParseIntError| e.to_string())?;
        let supplied = rationals::<2>(value)?;
        let mine = exact::half_pi_multiple(k);
        if supplied[0] > mine[0] || mine[1] > supplied[1] {
            failures.push(format!("half_pi_multiples[{key}] does not enclose k pi/2"));
        }
    }
    Ok(())
}

fn check_trig(
    trig: &Value,
    failures: &mut Vec<String>,
    counts: &mut BTreeMap<String, u64>,
) -> Check<()> {
    let values = trig["trig"].as_object().ok_or("trig must be object")?;
    let mut bad = 0;
    for (key, value) in values {
        let angle = exact::parse(key)?;
        let v = rationals::<6>(value)?;
        let encloses = |mine: &[Q; 4]| {
            v[0] <= mine[0] && mine[1] <= v[1] && v[2] <= mine[2] && mine[3] <= v[3]
        };
        let ok = encloses(&exact::cos_sin(&angle)) || encloses(&exact::cos_sin_bits(&angle, 2400));
        if !(ok && v[0] <= v[4] && v[4] <= v[1] && v[2] <= v[5] && v[5] <= v[3]) {
            bad += 1;
            if bad <= 5 {
                failures.push(format!("trig enclosure at {key} is not an enclosure"));
            }
        }
    }
    counts.insert(
        "trig_checked".into(),
        u64::try_from(values.len()).map_err(|e| e.to_string())?,
    );
    counts.insert("trig_bad".into(), bad);
    Ok(())
}

#[derive(Default)]
struct Tree {
    index: BTreeMap<u64, compact::Node>,
    values: compact::Values,
    children: BTreeMap<Option<u64>, Vec<u64>>,
    reasons: BTreeMap<String, u64>,
    closed: u64,
}
fn load_tree(options: &Options, manifest: &Value, failures: &mut Vec<String>) -> Check<Tree> {
    let mut tree = Tree::default();
    for (chunk_index, chunk) in array(&manifest["chunks"])?.iter().enumerate() {
        let data = read_named(&options.directory, text(chunk)?)?;
        for node in array(&data["nodes"])? {
            for key in ["id", "parent", "angles", "windows", "closed"] {
                if node.get(key).is_none() {
                    return Err(format!("malformed node: missing {key}"));
                }
            }
            let special = node["closed"] == "angle" || node["split"].get("tighten").is_some();
            if special && manifest["schema"] != "n17-subpattern-bb-certificate/v3" {
                return Err("schema: v3 feature in v1 tree".into());
            }
            if node["closed"] == "angle" && (node["final"].is_null() || !node["split"].is_null()) {
                return Err("T3: angle closure needs final and no split".into());
            }
            if manifest["schema"] == "n17-subpattern-bb-certificate/v3"
                && node["closed"].is_null()
                && !node["split"].is_null()
            {
                let split = node["split"].as_object().ok_or("T2: invalid split kind")?;
                if split.len() != 1
                    || !split
                        .keys()
                        .all(|k| matches!(k.as_str(), "angle" | "pair" | "tighten"))
                {
                    return Err("T2: invalid split kind".into());
                }
            }
            let ident = id(&node["id"])?;
            let parent = if node["parent"].is_null() {
                None
            } else {
                Some(id(&node["parent"])?)
            };
            let mut compact = compact::Node::new(node, &mut tree.values);
            compact.chunk = chunk_index;
            if tree.index.insert(ident, compact).is_some() {
                failures.push(format!("duplicate node id {ident}"));
            }
            tree.children.entry(parent).or_default().push(ident);
        }
    }
    tree.values.finish();
    check_tree(&mut tree, failures)?;
    Ok(tree)
}
fn sorted_windows(value: &Value) -> Check<Value> {
    let mut windows = array(value)?.clone();
    windows.sort_by_key(|v| {
        (
            v[0].as_u64(),
            v[1].as_str().map(str::to_owned),
            v[2].as_str().map(str::to_owned),
        )
    });
    Ok(Value::Array(windows))
}
fn state(node: &Value, sorted: bool) -> Check<String> {
    let windows = if sorted {
        sorted_windows(&node["windows"])?
    } else {
        node["windows"].clone()
    };
    Ok(json!([node["angles"], windows]).to_string())
}
fn expected_children(node: &Value) -> Check<Vec<String>> {
    let split = &node["split"];
    let mut result = vec![];
    if let Some(value) = split.get("tighten") {
        tighten::target(node)?;
        let mut child = node.clone();
        child["angles"] = value[1].clone();
        result.push(state(&child, true)?);
    } else if let Some(value) = split.get("angle") {
        let s = index(&value[0])?;
        let angles = array(&node["angles"])?;
        let angle = angles.get(s).ok_or("split angle index outside node")?;
        for part in [json!([angle[0], value[1]]), json!([value[1], angle[1]])] {
            let mut child = node.clone();
            child["angles"][s] = part;
            result.push(state(&child, false)?);
        }
    } else {
        let p = &split["pair"][0];
        for window in array(&split["pair"][1])? {
            let mut wins: Vec<_> = array(&node["windows"])?
                .iter()
                .filter(|v| v[0] != *p)
                .cloned()
                .collect();
            wins.push(json!([p, window[0], window[1]]));
            let mut child = node.clone();
            child["windows"] = Value::Array(wins);
            result.push(state(&child, true)?);
        }
    }
    result.sort();
    Ok(result)
}
fn check_tree(tree: &mut Tree, failures: &mut Vec<String>) -> Check<()> {
    let roots = tree.children.get(&None).cloned().unwrap_or_default();
    if roots.len() != 1 {
        failures.push(format!("T1: {} roots", roots.len()));
    }
    let mut stack: Vec<_> = roots.first().map(|root| (*root, 0)).into_iter().collect();
    while let Some((ident, depth)) = stack.pop() {
        if tree
            .index
            .get_mut(&ident)
            .expect("reachable node")
            .depth
            .replace(depth)
            .is_some()
        {
            return Err(format!("T3: node {ident} reached more than once"));
        }
        let node = &tree.index[&ident].json(&tree.values);
        let kids = tree.children.get(&Some(ident)).cloned().unwrap_or_default();
        if !node["closed"].is_null() {
            tree.closed += 1;
            *tree
                .reasons
                .entry(text(&node["closed"])?.into())
                .or_default() += 1;
            if !kids.is_empty() {
                failures.push(format!("T3: closed node {ident} has children"));
            }
            continue;
        }
        if node["split"].is_null() || node["final"].is_null() {
            failures.push(format!("T3: open node {ident} has no split or final"));
            continue;
        }
        let angle = node["split"].get("angle");
        if let Some(split) = angle {
            let s = index(&split[0])?;
            let interval = array(&node["angles"])?
                .get(s)
                .ok_or("angle split index outside node")?;
            let a = rational(&split[1])?;
            let span = rationals::<2>(interval)?;
            if a < span[0] || a > span[1] {
                failures.push(format!(
                    "T2: node {ident} angle split point outside the interval"
                ));
            }
        }
        let mut got = kids
            .iter()
            .map(|c| state(&tree.index[c].json(&tree.values), angle.is_none()))
            .collect::<Check<Vec<_>>>()?;
        got.sort();
        if got != expected_children(node)? {
            failures.push(format!(
                "T2: node {ident} {} split children mismatch",
                if angle.is_some() {
                    "angle"
                } else if node["split"].get("tighten").is_some() {
                    "tighten"
                } else {
                    "pair"
                }
            ));
        }
        stack.extend(kids.into_iter().map(|c| (c, depth + 1)));
    }
    let reached = tree
        .index
        .values()
        .filter(|node| node.depth.is_some())
        .count();
    if reached != tree.index.len() {
        failures.push(format!(
            "T3: {} nodes unreachable from the root",
            tree.index.len() - reached
        ));
    }
    Ok(())
}

fn check_nodes(
    options: &Options,
    manifest: &Value,
    verifier: &NodeVerifier,
    tree: &Tree,
    chosen: &BTreeSet<u64>,
    failures: &mut Vec<String>,
    counts: &mut BTreeMap<String, u64>,
) -> Check<(usize, usize)> {
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(options.threads)
        .build()
        .map_err(|e| e.to_string())?;
    let mut checked = 0;
    let mut failed = 0;
    let needed: BTreeSet<_> = chosen.iter().map(|ident| tree.index[ident].chunk).collect();
    let mut available = BTreeSet::new();
    for (chunk_index, chunk) in array(&manifest["chunks"])?.iter().enumerate() {
        if !needed.contains(&chunk_index) {
            continue;
        }
        let data = read_named(&options.directory, text(chunk)?)?;
        let mut nodes: Vec<_> = array(&data["nodes"])?
            .iter()
            .filter(|node| {
                node["id"]
                    .as_u64()
                    .is_some_and(|ident| chosen.contains(&ident))
            })
            .collect();
        nodes.sort_by_key(|node| node["id"].as_u64());
        for node in &nodes {
            available.insert(id(&node["id"])?);
        }
        // The oracle requires a parent to be loaded in this or an earlier chunk.
        nodes.retain(|node| {
            let parent = node["parent"].as_u64();
            if parent.is_some_and(|ident| !available.contains(&ident)) {
                failures.push(format!(
                    "node {}: parent {} not loaded",
                    node["id"], node["parent"]
                ));
                false
            } else {
                true
            }
        });
        let results: Vec<_> = pool.install(|| {
            nodes
                .par_iter()
                .map(|node| {
                    let parent = node["parent"].as_u64().and_then(|p| tree.index.get(&p));
                    let parent = parent.map(|p| p.parent(&tree.values));
                    let (ticks, result) = verifier.check_node(node, parent.as_ref());
                    (ticks, result)
                })
                .collect()
        });
        for (ticks, result) in results {
            checked += 1;
            for (key, count) in ticks {
                *counts.entry(key).or_default() += count;
            }
            if let Err(error) = result {
                failed += 1;
                failures.push(error);
            }
        }
        available.retain(|ident| tree.index[ident].open);
    }
    Ok((checked, failed))
}

fn run(options: &Options, receipt: &mut Value) -> Check<()> {
    if !exact::constants_hold() {
        return Err("the pi enclosure does not hold".into());
    }
    let name = if let Some(name) = &options.manifest {
        name.clone()
    } else {
        fs::read_to_string(options.directory.join("README.txt"))
            .map_err(|e| e.to_string())?
            .trim()
            .lines()
            .last()
            .ok_or("empty README")?
            .split(':')
            .next_back()
            .ok_or("missing manifest name")?
            .trim()
            .trim_end_matches(".json.gz")
            .to_string()
    };
    let manifest = read_named(&options.directory, &name)?;
    receipt["certificate"] =
        json!({"manifest_sha256":name,"chunks":array(&manifest["chunks"] )?.len()});
    receipt["pattern"] = manifest["header"]["pattern"].clone();
    let mut verifier = build_verifier(&manifest)?;
    let cells = load_cells(options)?;
    let mut failures = vec![];
    let mut counts = BTreeMap::new();
    check_header(&manifest, &verifier, &cells, &mut failures)?;
    counts.insert("header".into(), 1);
    let trig = read_named(&options.directory, text(&manifest["trig"])?)?;
    if verifier.v3 {
        verifier.trig_keys = trig["trig"]
            .as_object()
            .ok_or("trig must be object")?
            .keys()
            .cloned()
            .collect();
    }
    check_trig(&trig, &mut failures, &mut counts)?;
    drop(trig);
    let tree = load_tree(options, &manifest, &mut failures)?;
    if verifier.v3 {
        let tightening = tree
            .index
            .values()
            .filter(|n| n.json(&tree.values)["split"].get("tighten").is_some())
            .count();
        for (key, count) in [
            ("nodes", tree.index.len() as u64),
            ("leaves", tree.closed),
            ("tighten_nodes", tightening as u64),
            ("angle_leaves", *tree.reasons.get("angle").unwrap_or(&0)),
        ] {
            if manifest["summary"]
                .get(key)
                .is_some_and(|v| *v != json!(count))
            {
                failures.push(format!("summary.{key} mismatch"));
            }
        }
    }
    if manifest["summary"]["complete"] != true {
        failures.push("summary.complete is false".into());
    }
    let chosen: BTreeSet<u64> = if let Some(path) = &options.node_ids {
        let value: Value = serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        array(&value)?.iter().map(id).collect::<Check<_>>()?
    } else {
        tree.index.keys().copied().collect()
    };
    if chosen.iter().any(|i| !tree.index.contains_key(i)) {
        return Err("sample contains unknown node id".into());
    }
    let (checked, failed) = check_nodes(
        options,
        &manifest,
        &verifier,
        &tree,
        &chosen,
        &mut failures,
        &mut counts,
    )?;
    if options.node_ids.is_none() && checked != tree.index.len() {
        failures.push(format!("checked {checked} of {} nodes", tree.index.len()));
    }
    receipt["nodes"] = json!(tree.index.len());
    receipt["closed_leaves"] = json!(tree.closed);
    receipt["max_depth"] = json!(tree.index.values().filter_map(|node| node.depth).max());
    receipt["reasons"] = json!(tree.reasons);
    receipt["checked_nodes"] = json!(checked);
    receipt["node_failures"] = json!(failed);
    receipt["counts"] = json!(counts);
    receipt["status"] = json!(if failures.is_empty() { "PASS" } else { "FAIL" });
    receipt["failure_count"] = json!(failures.len());
    failures.truncate(50);
    receipt["failures"] = json!(failures);
    Ok(())
}
fn main() {
    let options = match Options::parse() {
        Ok(options) => options,
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(2)
        }
    };
    let clock = Instant::now();
    let mut receipt = json!({"schema":"n17-certificate-verification/v1","verifier":"branch-and-bound","directory":options.directory,"mode":if options.node_ids.is_some(){"sample"}else{"full"}});
    if let Err(error) = run(&options, &mut receipt) {
        receipt["status"] = json!("FAIL");
        receipt["failures"] = json!([error]);
        receipt["failure_count"] = json!(1);
    }
    receipt["seconds"] = json!((clock.elapsed().as_secs_f64() * 1000.0).round() / 1000.0);
    let output = match serde_json::to_string_pretty(&receipt) {
        Ok(output) => output,
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(2)
        }
    };
    if let Some(path) = &options.output
        && let Err(error) = fs::write(path, format!("{output}\n"))
    {
        eprintln!("write receipt: {error}");
        std::process::exit(2);
    }
    println!("{output}");
    if receipt["status"] != "PASS" {
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tree_tests {
    use super::*;

    fn split_tree() -> Tree {
        let root = json!({"id":0,"parent":null,"angles":[["0/1","2/1"]],"windows":[],"closed":null,"final":[],"split":{"angle":[0,"1/1"]}});
        let left = json!({"id":1,"parent":0,"angles":[["0/1","1/1"]],"windows":[],"closed":"disc"});
        let right =
            json!({"id":2,"parent":0,"angles":[["1/1","2/1"]],"windows":[],"closed":"disc"});
        let mut values = compact::Values::default();
        let index = [(0, root), (1, left), (2, right)]
            .into_iter()
            .map(|(id, node)| (id, compact::Node::new(&node, &mut values)))
            .collect();
        Tree {
            index,
            values,
            children: BTreeMap::from([(None, vec![0]), (Some(0), vec![1, 2])]),
            ..Tree::default()
        }
    }

    #[test]
    fn angle_children_must_partition_parent() {
        let mut tree = split_tree();
        let mut failures = vec![];
        check_tree(&mut tree, &mut failures).expect("valid tree");
        assert!(failures.is_empty());
        assert_eq!(tree.closed, 2);
        assert_eq!(tree.index[&2].depth, Some(1));
        let mut tree = split_tree();
        let mut child = tree.index[&2].json(&tree.values);
        child["angles"][0][0] = json!("3/2");
        tree.index
            .insert(2, compact::Node::new(&child, &mut tree.values));
        check_tree(&mut tree, &mut failures).expect("tree check");
        assert_eq!(failures, vec!["T2: node 0 angle split children mismatch"]);
    }

    #[test]
    fn tree_metadata_accepts_sparse_large_ids() {
        let mut tree = split_tree();
        let right = tree.index.remove(&2).expect("right child");
        tree.index.insert(u64::MAX, right);
        tree.children.insert(Some(0), vec![1, u64::MAX]);
        let mut failures = vec![];
        check_tree(&mut tree, &mut failures).expect("sparse tree");
        assert!(failures.is_empty());
        assert_eq!(tree.index[&u64::MAX].depth, Some(1));
        assert_eq!(tree.closed, 2);
    }

    #[test]
    fn unreachable_and_closed_children_are_rejected() {
        let mut tree = split_tree();
        let mut failures = vec![];
        tree.children.insert(Some(1), vec![3]);
        tree.index.insert(
            3,
            compact::Node::new(
                &json!({"id":3,"parent":1,"closed":"disc"}),
                &mut tree.values,
            ),
        );
        check_tree(&mut tree, &mut failures).expect("tree check");
        assert!(
            failures
                .iter()
                .any(|f| f == "T3: closed node 1 has children")
        );
        assert!(
            failures
                .iter()
                .any(|f| f == "T3: 1 nodes unreachable from the root")
        );
    }

    #[test]
    fn pair_children_compare_numeric_pair_indices_and_windows() {
        let node = json!({"angles":[["0/1","2/1"]],"windows":[[12,"0/1","1/1"],[2,"0/1","2/1"]],"split":{"pair":[2,[["0/1","1/1"],["1/1","2/1"]]]}});
        let expected = expected_children(&node).expect("pair children");
        let first = json!({"angles":[["0/1","2/1"]],"windows":[[2,"0/1","1/1"],[12,"0/1","1/1"]]});
        assert!(expected.contains(&state(&first, true).expect("state")));
    }
}
