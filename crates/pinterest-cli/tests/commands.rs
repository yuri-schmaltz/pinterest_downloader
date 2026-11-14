use std::process::Command;
#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;

#[test]
fn version_help_invalid_workers_and_missing_browser_have_stable_exits() {
    let binary = env!("CARGO_BIN_EXE_pinterest-cli");
    let version = Command::new(binary).arg("--version").output().unwrap();
    assert!(version.status.success());
    assert!(String::from_utf8_lossy(&version.stdout).contains(env!("CARGO_PKG_VERSION")));
    for flag in ["--workers", "--max-pins", "--collection-timeout"] {
        let output = Command::new(binary)
            .args(["alice", flag, "0"])
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2));
    }
    let output = Command::new(binary)
        .args(["alice", "--browser-executable", "/missing/chromium"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(3));
    let help = Command::new(binary).arg("--help").output().unwrap();
    let text = String::from_utf8_lossy(&help.stdout);
    for flag in [
        "--mode",
        "--headful",
        "--manual-login",
        "--json-log",
        "--log-file",
        "--scroll-pause",
        "--cache-dir",
        "--no-metadata-cache",
        "--end-quiet-rounds",
    ] {
        assert!(text.contains(flag));
    }
}

/// Two runs that share the same log file must not corrupt each other.
///
/// The file used to be truncated by both runs, so their bytes landed on top
/// of each other and a line came out as broken JSON.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn two_runs_that_share_a_log_file_keep_every_line_valid() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let log = directory.path().join("events.jsonl");
    let mut children = Vec::new();
    for _ in 0..2 {
        children.push(
            Command::new(env!("CARGO_BIN_EXE_pinterest-cli"))
                .args([
                    &format!("{}/snapshot/art/", server.url),
                    "--mode",
                    "http",
                    "--no-rate-limit",
                    "--output",
                    directory.path().join("out").to_str().unwrap(),
                    "--cache-dir",
                    directory.path().join("cache").to_str().unwrap(),
                    "--log-file",
                    log.to_str().unwrap(),
                ])
                .spawn()
                .unwrap(),
        );
    }
    for child in children {
        child.wait_with_output().unwrap();
    }
    let content = std::fs::read_to_string(&log).unwrap();
    let mut runs = std::collections::HashSet::new();
    for line in content.lines().filter(|line| !line.trim().is_empty()) {
        let event: serde_json::Value = serde_json::from_str(line)
            .unwrap_or_else(|error| panic!("the line is not valid JSON: {error}\n{line}"));
        runs.insert(event["run_id"].as_str().unwrap().to_owned());
    }
    assert_eq!(runs.len(), 2, "the two runs did not both leave their trace");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn http_json_stdout_is_parseable_and_partial_exit_is_explicit() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_pinterest-cli"))
        .args([
            &format!("{}/snapshot/art/", server.url),
            "--mode",
            "http",
            "--json-log",
            "--no-rate-limit",
            "--output",
            directory.path().to_str().unwrap(),
            "--cache-dir",
            directory.path().join("cache").to_str().unwrap(),
            "--log-file",
            directory.path().join("events.jsonl").to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert_eq!(
        output.status.code(),
        Some(6),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let events: Vec<serde_json::Value> = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(events.last().unwrap()["event"]["type"], "finished");
    assert_eq!(events.last().unwrap()["event"]["totals"]["downloaded"], 1);
    let persisted = std::fs::read_to_string(directory.path().join("events.jsonl")).unwrap();
    assert_eq!(persisted.lines().count(), events.len());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn native_cli_collects_dynamic_board_and_downloads_authenticated_media() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_pinterest-cli"))
        .args([
            &format!("{}/alice/art/", server.url),
            "--mode",
            "browser",
            "--no-sandbox",
            "--json-log",
            "--no-rate-limit",
            "--scroll-pause",
            "0.1",
            "--collection-timeout",
            "10",
            "--output",
            directory.path().to_str().unwrap(),
            "--cache-dir",
            directory.path().join("cache").to_str().unwrap(),
            "--log-file",
            directory.path().join("events.jsonl").to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert_eq!(
        output.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let events: Vec<serde_json::Value> = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(events.last().unwrap()["event"]["totals"]["downloaded"], 2);
    for id in ["101", "102"] {
        assert_eq!(
            std::fs::read(
                directory
                    .path()
                    .join("alice")
                    .join("art")
                    .join(format!("{id}.jpg"))
            )
            .unwrap(),
            b"fixture image"
        );
    }
}

/// Every option of the Python tool exists in the Rust tool.
///
/// The two tools are meant to be interchangeable. A flag that exists in one
/// and not in the other is a difference the user pays for.
#[test]
fn the_rust_cli_has_every_option_of_the_python_one() {
    let python = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../src/pinterest_board_dl.py"
    ))
    .unwrap();
    let mut flags: Vec<String> = Vec::new();
    let mut rest = python.as_str();
    while let Some(start) = rest.find("add_argument(") {
        let after = &rest[start + "add_argument(".len()..];
        let end = after.find(')').unwrap_or(after.len());
        let block = &after[..end];
        let mut word = block.split(|c: char| !(c.is_ascii_alphanumeric() || c == '-'));
        for piece in word.by_ref() {
            if piece.starts_with("--") && piece.len() > 2 {
                flags.push(piece.to_string());
            }
        }
        rest = &after[end..];
    }
    flags.sort();
    flags.dedup();
    assert!(
        flags.len() > 10,
        "the flags of the Python tool were not found"
    );

    let help = Command::new(env!("CARGO_BIN_EXE_pinterest-cli"))
        .arg("--help")
        .output()
        .unwrap();
    let text = String::from_utf8_lossy(&help.stdout);
    for flag in &flags {
        assert!(
            text.contains(flag.as_str()),
            "the Rust CLI does not have {flag}"
        );
    }
}
