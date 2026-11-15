//! A cancelled run stops promptly.
//!
//! The plan asks for the cancellation to be observed in at most two seconds,
//! without waiting for a network timeout, and gives the forced shutdown of a
//! stuck browser a separate limit of five seconds. The tests below observe
//! the cancellation instead of trusting the implementation.

use pinterest_core::engine::{run_target, CollectionMode, RunOptions};
use pinterest_core::models::DownloadOptions;
use pinterest_core::runtime::{Operation, RunEvent};
use pinterest_core::PinterestError;
use std::time::{Duration, Instant};

#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;

/// How long the plan allows for the cancellation to be observed.
const DEADLINE: Duration = Duration::from_secs(2);

fn options() -> RunOptions {
    RunOptions {
        mode: CollectionMode::Http,
        download: DownloadOptions {
            rate_limiting: false,
            metadata_cache: false,
            ..Default::default()
        },
        ..Default::default()
    }
}

#[tokio::test]
async fn a_cancelled_run_is_observed_within_two_seconds() {
    let server = fixture::serve().await;
    let (operation, mut events) = Operation::new(64);
    let cancel = operation.clone();
    let presenter = tokio::spawn(async move {
        while let Some(event) = events.recv().await {
            // The run starts while the board of the fixture is still being
            // fetched, so the cancellation lands in the middle of a request
            // that will never answer.
            if matches!(event.event, RunEvent::Started { .. }) {
                cancel.cancel();
            }
            if matches!(event.event, RunEvent::Cancelled) {
                return true;
            }
        }
        false
    });

    // The board of the fixture never answers, so the run can only end when
    // the cancellation is observed.
    let started = Instant::now();
    let result = tokio::time::timeout(
        DEADLINE,
        run_target(&format!("{}/slow/art/", server.url), options(), operation),
    )
    .await;
    let elapsed = started.elapsed();
    assert!(
        result.is_ok(),
        "the cancellation was not observed within {DEADLINE:?} (took {elapsed:?})"
    );
    assert!(matches!(result.unwrap(), Err(PinterestError::Cancelled)));
    assert!(
        presenter.await.unwrap(),
        "the terminal cancellation event never arrived"
    );
}

#[tokio::test]
async fn a_cancelled_run_before_the_work_starts_is_also_prompt() {
    let server = fixture::serve().await;
    let (operation, mut events) = Operation::new(64);
    let cancel = operation.clone();
    tokio::spawn(async move { while events.recv().await.is_some() {} });
    cancel.cancel();

    let started = Instant::now();
    let result = tokio::time::timeout(
        DEADLINE,
        run_target(
            &format!("{}/snapshot/art/", server.url),
            options(),
            operation,
        ),
    )
    .await;
    assert!(result.is_ok(), "the cancellation was not observed in time");
    assert!(matches!(result.unwrap(), Err(PinterestError::Cancelled)));
    assert!(started.elapsed() < DEADLINE);
}
