//! End-to-end checks of the binary on retained certificates.
//!
//! `small-certificate` is a complete 83-node certificate; each `mutated-*` copy changes one
//! field of it, and the verifier must reject that copy at the corresponding check.

use std::path::PathBuf;
use std::process::Command;

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}

fn run(name: &str) -> (i32, serde_json::Value) {
    let output = Command::new(env!("CARGO_BIN_EXE_n17bb-verify"))
        .arg(fixture(name))
        .args(["--threads", "2"])
        .output()
        .expect("the verifier binary runs");
    let receipt = serde_json::from_slice(&output.stdout).expect("the receipt is JSON");
    (output.status.code().expect("an exit code"), receipt)
}

fn first_failure(receipt: &serde_json::Value) -> String {
    receipt["failures"][0]
        .as_str()
        .unwrap_or_default()
        .to_owned()
}

#[test]
fn complete_certificate_passes() {
    let (code, receipt) = run("small-certificate");
    assert_eq!(code, 0);
    assert_eq!(receipt["status"], "PASS");
    assert_eq!(receipt["nodes"], 83);
    assert_eq!(receipt["node_failures"], 0);
}

#[test]
fn corrupted_certificates_fail_at_their_check() {
    for (name, needle) in [
        ("mutated-multiplier", "negative multiplier"),
        ("mutated-bound", "C4: bound on column"),
        ("mutated-cut", "C2: cut"),
        ("mutated-split", "T2:"),
        ("mutated-drop-leaf", "T2:"),
        ("mutated-narrow-final", "B2: final box too small"),
    ] {
        let (code, receipt) = run(name);
        assert_eq!(code, 1, "{name} must fail");
        assert_eq!(receipt["status"], "FAIL", "{name}");
        let failure = first_failure(&receipt);
        assert!(
            failure.contains(needle),
            "{name}: unexpected failure {failure:?}"
        );
    }
}

fn run_v3(name: &str) -> (i32, serde_json::Value) {
    use sha2::{Digest, Sha256};
    let cells = fixture("v3-cells.json");
    let digest = format!(
        "{:x}",
        Sha256::digest(std::fs::read(&cells).expect("cells"))
    );
    let output = Command::new(env!("CARGO_BIN_EXE_n17bb-verify"))
        .arg(fixture(name))
        .arg("--cells")
        .arg(cells)
        .args(["--cells-sha256", &digest, "--threads", "2"])
        .output()
        .expect("verifier");
    (
        output.status.code().expect("exit code"),
        serde_json::from_slice(&output.stdout).expect("receipt"),
    )
}

#[test]
fn v3_whole_trees_pass() {
    for (name, nodes, tightened) in [("v3-angle", 1, 0), ("v3-tighten", 2, 1)] {
        let (code, receipt) = run_v3(name);
        assert_eq!(code, 0, "{receipt}");
        assert_eq!(receipt["nodes"], nodes);
        assert_eq!(receipt["counts"]["closed_angle_ok"], 1);
        assert_eq!(
            receipt["counts"]["tighten_split_ok"].as_u64().unwrap_or(0),
            tightened
        );
    }
}

#[test]
fn v3_tampered_trees_fail_at_their_check() {
    for (name, message) in [
        ("drop-partner", "partner intervals do not cover alive set"),
        ("wall", "wall elimination not proved"),
        ("not-empty", "angle closure has no empty alive set"),
        ("wrong-pair", "invalid elimination pair"),
        ("repeat", "elimination does not meet alive set"),
        ("missing-trig", "elimination angle missing from trig table"),
        ("small-final", "final box too small"),
        ("in-v1", "v3 feature in v1 tree"),
        ("summary", "summary.tighten_nodes mismatch"),
        ("target", "tighten target does not contain alive set"),
        ("child-window", "tighten split children mismatch"),
    ] {
        let (code, receipt) = run_v3(&format!("v3-{name}"));
        assert_eq!(code, 1, "{receipt}");
        assert!(first_failure(&receipt).contains(message), "{receipt}");
    }
}
