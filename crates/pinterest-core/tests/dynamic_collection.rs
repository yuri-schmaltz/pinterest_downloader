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
async fn a_slow_feed_is_not_reported_as_an_empty_board() {
    // The page looks unchanged while the first payload is still on its way.
    // A collector that concludes "stable" on that silence reports an empty
    // board, which is a wrong answer rather than an incomplete one. It has to
    // wait for the request that is in flight.
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let board = collector
        .collect_board(&format!("{}/alice/slow/art/", server.url))
        .await
        .unwrap();
    assert!(
        !board.pin_links.is_empty(),
        "a slow feed was reported as an empty board"
    );
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
        std::fs::read(directory.path().join("dom").join("art").join("103.jpg")).unwrap(),
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
        // A cold Windows runner needs a while to start Chromium; the test
        // checks cancellation semantics, not how fast the browser boots.
        Duration::from_secs(60),
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

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn the_recommended_pins_are_not_part_of_the_board() {
    // The page of the board carries the pins of the board and, next to them,
    // the pins that Pinterest recommends. A recommendation is not part of
    // the board and must not be downloaded as one.
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let board = collector
        .collect_board(&format!("{}/origin/art/", server.url))
        .await
        .unwrap();
    let mut ids: Vec<_> = board.pin_links.keys().cloned().collect();
    ids.sort();
    assert_eq!(ids, ["601", "602"]);
    assert_eq!(board.origin.excluded_recommendations, 1);
    assert_eq!(board.origin.sources.get("board-feed"), Some(&1));
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn a_board_that_never_ends_reports_the_timeout_as_a_partial_result() {
    // The feed of this board never says that it ended. The collection has to
    // stop on its own timeout, and the report has to say that the result is
    // partial instead of pretending the board is complete.
    let server = fixture::serve().await;
    let collector = Collector::launch(
        CollectionOptions {
            max_duration: Duration::from_secs(3),
            ..options()
        },
        operation(),
    )
    .await
    .unwrap();
    let board = collector
        .collect_board(&format!("{}/neverend/art/", server.url))
        .await
        .unwrap();
    assert_eq!(board.reason, CompletionReason::Timeout);
    assert_eq!(board.completeness, Completeness::Unknown);
    assert_eq!(board.pin_links.len(), 1);
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium and a display; the CI runs it under a virtual display"]
async fn a_page_that_always_asks_for_a_login_cannot_keep_the_run_forever() {
    // Every prompt for a login used to push the deadline away, so a page
    // that always asks for a login never ended. The collection has to stop
    // on the timeout it was given.
    if cfg!(target_os = "linux") && std::env::var_os("DISPLAY").is_none() {
        eprintln!("pulado: esta maquina nao tem display para o browser visivel");
        return;
    }
    let server = fixture::serve().await;
    let (operation, mut events) = Operation::new(32);
    let resume = operation.clone();
    tokio::spawn(async move {
        while let Some(event) = events.recv().await {
            if matches!(event.event, RunEvent::LoginRequired { .. }) {
                resume.resume_login();
            }
        }
    });
    let collector = Collector::launch(
        CollectionOptions {
            manual_login: true,
            max_duration: Duration::from_secs(3),
            ..options()
        },
        operation,
    )
    .await
    .unwrap();
    let result = tokio::time::timeout(
        Duration::from_secs(30),
        collector.collect_board(&format!("{}/login/", server.url)),
    )
    .await;
    assert!(result.is_ok(), "the collection never ended");
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn a_board_that_stops_without_saying_it_ended_is_not_complete() {
    // The feed stopped changing, but nothing proved that the board is
    // complete. The stability is not proof: the result stays unknown.
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let board = collector
        .collect_board(&format!("{}/still/art/", server.url))
        .await
        .unwrap();
    assert_eq!(board.reason, CompletionReason::Stable);
    assert_eq!(board.completeness, Completeness::Unknown);
    assert_eq!(board.pin_links.len(), 1);
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn a_real_public_board_asks_for_a_login_instead_of_saying_it_is_empty() {
    // Captura real e sanitizada de um quadro publico do Pinterest. Sem
    // sessao, a pagina entrega os pins bloqueados e o feed vazio. Dizer
    // "nenhum pin encontrado" seria uma resposta errada: o quadro tem pins,
    // quem nao esta logado e que nao os ve.
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let result = collector
        .collect_board(&format!("{}/real/public/", server.url))
        .await;
    assert!(
        matches!(
            result,
            Err(pinterest_core::PinterestError::AuthenticationRequired(_))
        ),
        "a gated board did not ask for a login: {result:?}"
    );
    collector.close().await.unwrap();
}
