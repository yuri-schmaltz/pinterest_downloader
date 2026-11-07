//! The pin metadata cache must save a network round trip without changing
//! what is downloaded.
//!
//! The cache is consulted for pins that still need resolution, and every
//! resolved pin is written back. A second run over the same cache directory
//! must not ask the pin page again.

use pinterest_core::cache::{resolve_cache_dir, PinCache};
use std::sync::atomic::Ordering;
use std::time::Duration;

#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;

use pinterest_core::collector::CollectionOptions;
use pinterest_core::engine::{run_target, RunOptions};
use pinterest_core::models::DownloadOptions;
use pinterest_core::runtime::Operation;

fn collection() -> CollectionOptions {
    let mut options = CollectionOptions {
        scroll_pause: Duration::from_millis(120),
        stable_rounds: 4,
        max_duration: Duration::from_secs(10),
        ..Default::default()
    };
    options.browser.no_sandbox = true;
    options
}

/// An operation whose event channel is drained until the run terminates.
fn operation() -> Operation {
    let (operation, mut events) = Operation::new(32);
    tokio::spawn(async move { while events.recv().await.is_some() {} });
    operation
}

#[tokio::test]
async fn cache_round_trips_metadata_and_survives_a_corrupt_file() {
    let directory = tempfile::tempdir().unwrap();

    let mut cache = PinCache::load(directory.path());
    assert!(cache.is_empty());
    cache.insert(
        "https://www.pinterest.com/pin/1/",
        "https://i.pinimg.com/1.jpg",
    );
    cache.save().await.unwrap();

    let stored = directory.path().join(".pinterest_cache.json");
    assert!(stored.is_file(), "the cache file was not written");
    assert!(
        !directory.path().join(".pinterest_cache.json.part").exists(),
        "the temporary cache file was left behind"
    );

    let reloaded = PinCache::load(directory.path());
    assert_eq!(
        reloaded.get("https://www.pinterest.com/pin/1/"),
        Some("https://i.pinimg.com/1.jpg")
    );
    assert_eq!(reloaded.len(), 1);

    // A corrupt file must not break the run; it is discarded instead.
    std::fs::write(&stored, "this is not json").unwrap();
    let after_corruption = PinCache::load(directory.path());
    assert!(after_corruption.is_empty());
}

#[tokio::test]
async fn the_cache_file_is_shared_with_the_python_format() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join(".pinterest_cache.json");
    // The Python CLI writes a plain JSON object of pin URL -> media URL.
    std::fs::write(
        &path,
        r#"{"https://www.pinterest.com/pin/1/": "https://i.pinimg.com/1.jpg"}"#,
    )
    .unwrap();

    let cache = PinCache::load(directory.path());
    assert_eq!(
        cache.get("https://www.pinterest.com/pin/1/"),
        Some("https://i.pinimg.com/1.jpg")
    );
}

#[tokio::test]
async fn an_explicit_cache_directory_overrides_the_platform_default() {
    let chosen = resolve_cache_dir(Some(std::path::Path::new("/tmp/explicit-cache")));
    assert_eq!(chosen, std::path::PathBuf::from("/tmp/explicit-cache"));
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn a_second_run_reuses_the_cached_media_url() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let cache_dir = directory.path().join("cache");

    let options = || RunOptions {
        collection: collection(),
        download: DownloadOptions {
            out_root: directory.path().join("downloads"),
            rate_limiting: false,
            cache_dir: Some(cache_dir.clone()),
            ..Default::default()
        },
        ..Default::default()
    };

    let first = run_target(&format!("{}/dom/art/", server.url), options(), operation())
        .await
        .unwrap();
    assert_eq!(first.totals.resolved, 1);
    assert_eq!(first.totals.failed, 0);

    let hits_after_first = server.pin_hits.load(Ordering::SeqCst);
    assert!(
        hits_after_first > 0,
        "the first run must resolve the pin over the network"
    );

    let cache_file = cache_dir.join(".pinterest_cache.json");
    assert!(cache_file.is_file(), "the cache file was not written");
    let stored = std::fs::read_to_string(&cache_file).unwrap();
    assert!(
        stored.contains("/pin/103/"),
        "the resolved pin is not in the cache"
    );

    // Second run: the same cache directory must answer without asking the
    // pin page again.
    let second = run_target(&format!("{}/dom/art/", server.url), options(), operation())
        .await
        .unwrap();
    assert_eq!(second.totals.resolved, 1);
    assert_eq!(second.totals.failed, 0);
    assert_eq!(
        server.pin_hits.load(Ordering::SeqCst),
        hits_after_first,
        "the cached pin was resolved over the network again"
    );
}

#[tokio::test]
#[ignore = "requires Chromium; browser CI runs explicitly"]
async fn disabling_the_metadata_cache_never_writes_the_file() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let cache_dir = directory.path().join("cache");

    let options = RunOptions {
        collection: collection(),
        download: DownloadOptions {
            out_root: directory.path().join("downloads"),
            rate_limiting: false,
            cache_dir: Some(cache_dir.clone()),
            metadata_cache: false,
            ..Default::default()
        },
        ..Default::default()
    };

    let report = run_target(&format!("{}/dom/art/", server.url), options, operation())
        .await
        .unwrap();
    assert_eq!(report.totals.resolved, 1);
    assert!(
        !cache_dir.join(".pinterest_cache.json").exists(),
        "the cache file was written even with the metadata cache disabled"
    );
}
