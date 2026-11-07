#![cfg(feature = "browser")]
use pinterest_core::{
    collector::{CollectionOptions, Collector},
    engine::{run_target, CollectionMode, RunOptions},
    runtime::{Completeness, CompletionReason},
    DownloadOptions, Operation, RunEvent,
};
use std::time::Duration;
#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;

fn options() -> CollectionOptions {
    let mut options = CollectionOptions {
        scroll_pause: Duration::from_millis(120),
        stable_rounds: 4,
        max_duration: Duration::from_secs(10),
        ..Default::default()
    };
    options.browser.no_sandbox = true;
    options
}
fn operation() -> Operation {
    let (operation, mut events) = Operation::new(32);
    tokio::spawn(async move { while events.recv().await.is_some() {} });
    operation
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn virtualized_feed_accumulates_exact_network_pin_ids() {
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let board = collector
        .collect_board(&format!("{}/alice/art/", server.url))
        .await
        .unwrap();
    let expected: serde_json::Value =
        serde_json::from_str(include_str!("../../../tests/fixtures/parity/expected.json")).unwrap();
    assert_eq!(
        serde_json::json!(board.pins.keys().collect::<Vec<_>>()),
        expected["dynamic_board"]["pin_ids"]
    );
    assert_eq!(board.completeness, Completeness::Complete);
    assert_eq!(board.reason, CompletionReason::EndOfFeed);
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn profile_excludes_other_users_and_includes_late_board() {
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let profile = collector
        .collect_profile(&format!("{}/alice/", server.url))
        .await
        .unwrap();
    assert_eq!(profile.boards.len(), 2);
    assert!(profile.boards[0].url.ends_with("/alice/art/"));
    assert!(profile.boards[1].url.ends_with("/alice/nature/"));
    assert_eq!(profile.completeness, Completeness::Unknown);
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn limit_stops_per_board_and_empty_feed_is_a_distinct_success() {
    let server = fixture::serve().await;
    let collector = Collector::launch(
        CollectionOptions {
            max_pins: Some(1),
            ..options()
        },
        operation(),
    )
    .await
    .unwrap();
    let board = collector
        .collect_board(&format!("{}/alice/art/", server.url))
        .await
        .unwrap();
    assert_eq!(board.pin_links.len(), 1);
    assert_eq!(board.completeness, Completeness::Limited);
    let empty = collector
        .collect_board(&format!("{}/empty/art/", server.url))
        .await
        .unwrap();
    assert!(empty.pin_links.is_empty());
    assert_eq!(empty.completeness, Completeness::Complete);
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn runner_transfers_browser_cookies_downloads_and_reports_cache_hits() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    for cached in [false, true] {
        let opts = RunOptions {
            collection: options(),
            download: DownloadOptions {
                out_root: directory.path().to_owned(),
                rate_limiting: false,
                cache_dir: Some(directory.path().join("cache")),
                ..Default::default()
            },
            ..Default::default()
        };
        let (operation, mut events) = Operation::new(32);
        let presenter = tokio::spawn(async move {
            let mut terminal = 0;
            while let Some(event) = events.recv().await {
                if matches!(event.event, RunEvent::Finished { .. }) {
                    terminal += 1;
                    break;
                }
            }
            terminal
        });
        let report = run_target(&format!("{}/alice/art/", server.url), opts, operation)
            .await
            .unwrap();
        assert_eq!(presenter.await.unwrap(), 1);
        assert_eq!(report.totals.discovered, 2);
        assert_eq!(report.totals.failed, 0);
        assert_eq!(report.totals.downloaded, if cached { 0 } else { 2 });
        assert_eq!(report.totals.reused, if cached { 2 } else { 0 });
        for id in ["101", "102"] {
            assert_eq!(
                std::fs::read(directory.path().join("alice_art").join(format!("{id}.jpg")))
                    .unwrap(),
                b"fixture image"
            );
        }
    }
}

#[tokio::test]
async fn explicit_http_snapshot_cannot_claim_completeness() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let opts = RunOptions {
        mode: CollectionMode::Http,
        download: DownloadOptions {
            out_root: directory.path().to_owned(),
            rate_limiting: false,
            cache_dir: Some(directory.path().join("cache")),
            ..Default::default()
        },
        ..Default::default()
    };
    let report = run_target(&format!("{}/snapshot/art/", server.url), opts, operation())
        .await
        .unwrap();
    assert_eq!(report.boards[0].reason, CompletionReason::Snapshot);
    assert_eq!(report.boards[0].completeness, Completeness::Unknown);
    assert_eq!(report.totals.downloaded, 1);
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn resolves_dom_only_pin_using_its_page_and_session() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let opts = RunOptions {
        collection: options(),
        download: DownloadOptions {
            out_root: directory.path().to_owned(),
            rate_limiting: false,
            cache_dir: Some(directory.path().join("cache")),
            ..Default::default()
        },
        ..Default::default()
    };
    let report = run_target(&format!("{}/dom/art/", server.url), opts, operation())
        .await
        .unwrap();
    assert_eq!(report.totals.discovered, 1);
    assert_eq!(report.totals.resolved, 1);
    assert_eq!(report.totals.downloaded, 1);
    assert_eq!(report.totals.failed, 0);
    assert_eq!(
        std::fs::read(directory.path().join("dom_art/103.jpg")).unwrap(),
        b"fixture image"
    );
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn cancelled_run_drains_terminal_event_and_closes_browser() {
    let server = fixture::serve().await;
    let (operation, mut events) = Operation::new(4);
    let cancel = operation.clone();
    let presenter = tokio::spawn(async move {
        while let Some(event) = events.recv().await {
            if matches!(event.event, RunEvent::CollectionProgress { .. }) {
                cancel.cancel();
            }
            if matches!(event.event, RunEvent::Cancelled) {
                return true;
            }
        }
        false
    });
    let result = tokio::time::timeout(
        Duration::from_secs(5),
        run_target(
            &format!("{}/alice/art/", server.url),
            RunOptions {
                collection: options(),
                ..Default::default()
            },
            operation,
        ),
    )
    .await
    .unwrap();
    assert!(matches!(
        result,
        Err(pinterest_core::PinterestError::Cancelled)
    ));
    assert!(presenter.await.unwrap());
}
