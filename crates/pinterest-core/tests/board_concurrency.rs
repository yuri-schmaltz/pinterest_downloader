//! The board worker pool must really overlap the boards.
//!
//! The fixture server records the highest number of requests it handled at
//! the same time, so the concurrency is observed instead of assumed. These
//! tests run in HTTP mode, which needs no browser.

use pinterest_core::engine::{run_target, CollectionMode, RunOptions};
use pinterest_core::models::DownloadOptions;
use pinterest_core::runtime::Operation;
use std::sync::atomic::Ordering;

#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;

/// An operation whose event channel is drained until the run terminates.
fn operation() -> Operation {
    let (operation, mut events) = Operation::new(64);
    tokio::spawn(async move { while events.recv().await.is_some() {} });
    operation
}

fn options(out_root: &std::path::Path, boards_workers: usize) -> RunOptions {
    RunOptions {
        mode: CollectionMode::Http,
        download: DownloadOptions {
            out_root: out_root.to_owned(),
            rate_limiting: false,
            boards_workers,
            cache_dir: Some(out_root.join("cache")),
            ..Default::default()
        },
        ..Default::default()
    }
}

#[tokio::test]
async fn boards_workers_decides_how_many_boards_run_at_the_same_time() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();

    let sequential = run_target(
        &format!("{}/profile-many/", server.url),
        options(&directory.path().join("sequential"), 1),
        operation(),
    )
    .await
    .unwrap();
    assert_eq!(
        sequential.boards.len(),
        3,
        "the three boards were not found"
    );
    assert_eq!(
        server.peak_concurrency.load(Ordering::SeqCst),
        1,
        "one worker must not overlap the boards"
    );

    let parallel = run_target(
        &format!("{}/profile-many/", server.url),
        options(&directory.path().join("parallel"), 3),
        operation(),
    )
    .await
    .unwrap();
    assert_eq!(parallel.boards.len(), 3);
    assert!(
        server.peak_concurrency.load(Ordering::SeqCst) >= 2,
        "three workers did not overlap the boards, peak was {}",
        server.peak_concurrency.load(Ordering::SeqCst)
    );
}

#[tokio::test]
async fn the_board_order_follows_the_discovery_and_not_the_completion() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let report = run_target(
        &format!("{}/profile-many/", server.url),
        options(&directory.path().join("downloads"), 3),
        operation(),
    )
    .await
    .unwrap();
    let names: Vec<String> = report
        .boards
        .iter()
        .map(|board| {
            board
                .board_url
                .rsplit('/')
                .nth(1)
                .unwrap_or_default()
                .to_string()
        })
        .collect();
    assert_eq!(
        names,
        // Sorted by URL, so the report is stable between runs.
        vec!["one", "three", "two"],
        "the boards were reported out of the discovered order"
    );
}

#[tokio::test]
async fn a_zero_boards_workers_is_an_error() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let result = run_target(
        &format!("{}/profile-many/", server.url),
        options(&directory.path().join("downloads"), 0),
        operation(),
    )
    .await;
    assert!(result.is_err(), "zero boards workers must be refused");
}
