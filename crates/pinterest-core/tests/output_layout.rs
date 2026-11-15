//! The output layout is shared with the Python tool and the totals add up.
//!
//! The Python tool writes `<out_root>/<user>/<board>`; an earlier Rust build
//! wrote `<out_root>/<user>_<board>`. The engine has to migrate the old
//! directory instead of downloading everything again, and the totals of a run
//! must reconcile with the files that are on disk.

use pinterest_core::engine::{run_target, CollectionMode, RunOptions};
use pinterest_core::models::DownloadOptions;
use pinterest_core::runtime::Operation;
use std::sync::atomic::Ordering;

#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;

fn operation() -> Operation {
    let (operation, mut events) = Operation::new(64);
    tokio::spawn(async move { while events.recv().await.is_some() {} });
    operation
}

fn options(out_root: &std::path::Path) -> RunOptions {
    RunOptions {
        mode: CollectionMode::Http,
        download: DownloadOptions {
            out_root: out_root.to_owned(),
            rate_limiting: false,
            metadata_cache: false,
            ..Default::default()
        },
        ..Default::default()
    }
}

#[tokio::test]
async fn the_board_lands_in_the_layout_shared_with_the_python_tool() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let report = run_target(
        &format!("{}/snapshot/art/", server.url),
        options(directory.path()),
        operation(),
    )
    .await
    .unwrap();
    assert_eq!(report.boards.len(), 1);
    let board_dir = directory.path().join("snapshot").join("art");
    assert!(
        board_dir.is_dir(),
        "the board did not use the shared layout"
    );
    assert!(board_dir.join("101.jpg").is_file());
    assert_eq!(report.boards[0].output_dir, board_dir);
}

#[tokio::test]
async fn the_totals_reconcile_with_the_files_on_disk() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let report = run_target(
        &format!("{}/snapshot/art/", server.url),
        options(directory.path()),
        operation(),
    )
    .await
    .unwrap();
    let totals = report.totals;
    assert!(totals.discovered > 0);
    // Every discovered pin is accounted for exactly once.
    assert_eq!(
        totals.downloaded + totals.reused + totals.failed,
        totals.discovered,
        "the totals do not reconcile: {totals:?}"
    );
    // A pin only counts as verified when the file is really there.
    assert_eq!(totals.verified, totals.downloaded + totals.reused);
    // And the verified files exist on disk.
    let files = walk(&report.boards[0].output_dir);
    assert_eq!(files, totals.verified);
}

#[tokio::test]
async fn the_legacy_layout_is_migrated_instead_of_downloaded_again() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    // The old Rust layout: a single directory named `<user>_<board>`.
    let legacy = directory.path().join("snapshot_art");
    std::fs::create_dir_all(&legacy).unwrap();
    std::fs::write(legacy.join("101.jpg"), b"already downloaded").unwrap();

    let report = run_target(
        &format!("{}/snapshot/art/", server.url),
        options(directory.path()),
        operation(),
    )
    .await
    .unwrap();
    let totals = report.totals;
    // The file was already there, so nothing was downloaded again.
    assert_eq!(totals.downloaded, 0, "the file was downloaded twice");
    assert_eq!(totals.reused, 1);
    assert_eq!(totals.failed, 0);
    // And the media was never requested from the network.
    assert_eq!(server.pin_hits.load(Ordering::SeqCst), 0);

    // The old directory moved to the shared layout, keeping the file.
    let migrated = directory.path().join("snapshot").join("art");
    assert!(migrated.is_dir(), "the legacy directory was not migrated");
    assert_eq!(
        std::fs::read(migrated.join("101.jpg")).unwrap(),
        b"already downloaded"
    );
    assert!(!legacy.exists(), "the legacy directory was left behind");
}

#[tokio::test]
async fn a_legacy_file_is_reused_even_when_the_new_directory_already_exists() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let legacy = directory.path().join("snapshot_art");
    std::fs::create_dir_all(&legacy).unwrap();
    std::fs::write(legacy.join("404.jpg"), b"from the old layout").unwrap();
    let current = directory.path().join("snapshot").join("art");
    std::fs::create_dir_all(&current).unwrap();

    let report = run_target(
        &format!("{}/snapshot/art/", server.url),
        options(directory.path()),
        operation(),
    )
    .await
    .unwrap();
    // The pin of the board was downloaded, the file of the old layout that
    // belongs to another pin was left alone.
    assert_eq!(report.totals.downloaded, 1);
    assert!(current.join("101.jpg").is_file());
    assert_eq!(
        std::fs::read(legacy.join("404.jpg")).unwrap(),
        b"from the old layout"
    );
}

fn walk(directory: &std::path::Path) -> usize {
    let Ok(entries) = std::fs::read_dir(directory) else {
        return 0;
    };
    entries
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.path().is_file())
        .count()
}
