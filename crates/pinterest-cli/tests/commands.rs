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
    ] {
        assert!(text.contains(flag));
    }
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
            std::fs::read(directory.path().join("alice_art").join(format!("{id}.jpg"))).unwrap(),
            b"fixture image"
        );
    }
}
