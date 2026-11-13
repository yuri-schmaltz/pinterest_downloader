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
async fn only_the_pins_of_the_target_board_belong_to_it() {
    // The page of a board also asks for the feeds of other boards. The pin
    // that names another board does not belong to the target and must not be
    // downloaded as if it were.
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let board = collector
        .collect_board(&format!("{}/mixed/art/", server.url))
        .await
        .unwrap();
    let mut ids: Vec<_> = board.pin_links.keys().cloned().collect();
    ids.sort();
    assert_eq!(
        ids,
        ["801", "803"],
        "a pin of another board was counted as part of the target"
    );
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn the_same_pin_that_arrives_three_ways_is_counted_once() {
    // The pin shows up in the DOM, in the network payload and in the DOM
    // again after the scroll. The exact id has to be there, and only once.
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let board = collector
        .collect_board(&format!("{}/dupes/art/", server.url))
        .await
        .unwrap();
    let mut ids: Vec<_> = board.pin_links.keys().cloned().collect();
    ids.sort();
    assert_eq!(ids, ["901"]);
    assert_eq!(board.pins.len(), 1);
    assert_eq!(board.pins["901"].id, "901");
    // The pin came from the DOM and from the network, and it was counted
    // once all the same.
    assert_eq!(board.origin.sources.values().sum::<usize>(), 1);
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium and a display; the CI runs it under a virtual display"]
async fn a_session_that_expires_midway_keeps_the_pins_that_were_already_collected() {
    // The session expires after the first pins arrive. The user logs in and
    // the collection continues; the pins collected before the expiry stay.
    if cfg!(target_os = "linux") && std::env::var_os("DISPLAY").is_none() {
        eprintln!("pulado: esta maquina nao tem display para o browser visivel");
        return;
    }
    let server = fixture::serve().await;
    let (operation, mut events) = Operation::new(32);
    let resume = operation.clone();
    let login_prompts = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let counter = std::sync::Arc::clone(&login_prompts);
    tokio::spawn(async move {
        while let Some(event) = events.recv().await {
            if matches!(event.event, RunEvent::LoginRequired { .. }) {
                counter.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                resume.resume_login();
            }
        }
    });
    let collector = Collector::launch(
        CollectionOptions {
            manual_login: true,
            max_duration: Duration::from_secs(6),
            ..options()
        },
        operation,
    )
    .await
    .unwrap();
    let board = collector
        .collect_board(&format!("{}/session-expired/art/", server.url))
        .await
        .unwrap();
    let mut ids: Vec<_> = board.pin_links.keys().cloned().collect();
    ids.sort();
    assert_eq!(
        ids,
        ["1001", "1002"],
        "the pins collected before the session expired were lost"
    );
    assert!(
        login_prompts.load(std::sync::atomic::Ordering::SeqCst) >= 1,
        "the expired session never asked for a login"
    );
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium and a display; the CI runs it under a virtual display"]
async fn cancelling_the_login_stops_the_run_right_away() {
    // The user refuses to log in. The run has to stop promptly instead of
    // waiting for the deadline, and it must not leave the browser behind.
    if cfg!(target_os = "linux") && std::env::var_os("DISPLAY").is_none() {
        eprintln!("pulado: esta maquina nao tem display para o browser visivel");
        return;
    }
    let server = fixture::serve().await;
    let (operation, mut events) = Operation::new(32);
    let cancel = operation.clone();
    tokio::spawn(async move {
        while let Some(event) = events.recv().await {
            if matches!(event.event, RunEvent::LoginRequired { .. }) {
                cancel.cancel();
            }
        }
    });
    let collector = Collector::launch(
        CollectionOptions {
            manual_login: true,
            max_duration: Duration::from_secs(120),
            ..options()
        },
        operation,
    )
    .await
    .unwrap();
    let started = std::time::Instant::now();
    let result = collector
        .collect_board(&format!("{}/session-expired/art/", server.url))
        .await;
    assert!(
        matches!(result, Err(pinterest_core::PinterestError::Cancelled)),
        "the run did not stop: {result:?}"
    );
    assert!(
        started.elapsed() < Duration::from_secs(10),
        "cancelling the login took {:?}",
        started.elapsed()
    );
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn one_browser_serves_every_board_of_the_run() {
    // Opening a Chromium per board is slow and heavy. The same browser has
    // to serve the whole run: the pid before the first board and the pid
    // after the last one have to be the same, and the process has to be
    // gone once the collector is closed.
    let server = fixture::serve().await;
    let collector = Collector::launch(options(), operation()).await.unwrap();
    let first = collector.process_id().expect("the browser has no pid");

    let first_board = collector
        .collect_board(&format!("{}/alice/art/", server.url))
        .await
        .unwrap();
    assert_eq!(first_board.pin_links.len(), 2);
    assert_eq!(
        collector.process_id(),
        Some(first),
        "the browser was replaced between two boards"
    );

    let second_board = collector
        .collect_board(&format!("{}/alice/nature/", server.url))
        .await
        .unwrap();
    assert!(!second_board.pin_links.is_empty());
    assert_eq!(
        collector.process_id(),
        Some(first),
        "the browser was replaced between two boards"
    );

    collector.close().await.unwrap();
    #[cfg(target_os = "linux")]
    assert!(
        !std::path::Path::new(&format!("/proc/{first}")).exists(),
        "the browser was not reaped"
    );
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn a_board_that_says_it_ended_does_not_wait_for_the_whole_stability_budget() {
    // The page tells the collector that the feed ended. That is evidence
    // that there is nothing more to load, so waiting the whole stability
    // budget (20 rounds) added half a minute to every single board.
    let server = fixture::serve().await;
    let collector = Collector::launch(
        CollectionOptions {
            scroll_pause: Duration::from_millis(200),
            stable_rounds: 20,
            max_duration: Duration::from_secs(30),
            ..options()
        },
        operation(),
    )
    .await
    .unwrap();
    let started = std::time::Instant::now();
    let board = collector
        .collect_board(&format!("{}/alice/art/", server.url))
        .await
        .unwrap();
    let elapsed = started.elapsed();
    assert_eq!(board.reason, CompletionReason::EndOfFeed);
    assert_eq!(board.completeness, Completeness::Complete);
    assert_eq!(board.pin_links.len(), 2);
    assert!(
        elapsed < Duration::from_secs(5),
        "a board that said it ended took {elapsed:?}"
    );
    collector.close().await.unwrap();
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn a_board_without_the_end_marker_still_waits_for_the_stability_budget() {
    // The fast path belongs to the end marker alone. A board that merely
    // stopped changing has no proof that it is complete, so it keeps the
    // whole budget and reports the result as unknown.
    let server = fixture::serve().await;
    let collector = Collector::launch(
        CollectionOptions {
            scroll_pause: Duration::from_millis(200),
            stable_rounds: 8,
            max_duration: Duration::from_secs(30),
            ..options()
        },
        operation(),
    )
    .await
    .unwrap();
    let started = std::time::Instant::now();
    let board = collector
        .collect_board(&format!("{}/still/art/", server.url))
        .await
        .unwrap();
    let elapsed = started.elapsed();
    assert_eq!(board.reason, CompletionReason::Stable);
    assert_eq!(board.completeness, Completeness::Unknown);
    assert!(
        elapsed >= Duration::from_millis(8 * 200),
        "the stability budget was skipped: {elapsed:?}"
    );
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
