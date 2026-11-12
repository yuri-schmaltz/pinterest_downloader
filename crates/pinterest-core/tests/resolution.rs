//! A pin is always resolved as the same pin.
//!
//! The plan asks for a fallback that does not change the identity of the
//! pin: when the URL of the media expired, the pin is resolved again and the
//! file keeps the name of the same pin. The mobile domain is the fallback
//! the Python tool already uses.

use pinterest_core::engine::{run_target, CollectionMode, RunOptions};
use pinterest_core::models::DownloadOptions;
use pinterest_core::runtime::Operation;

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
async fn an_expired_media_url_is_resolved_again_under_the_same_pin() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let report = run_target(
        &format!("{}/expire/art/", server.url),
        options(directory.path()),
        operation(),
    )
    .await
    .unwrap();

    // The pin was downloaded, and the file carries the name of the pin.
    assert_eq!(report.totals.downloaded, 1, "{:?}", report.totals);
    assert_eq!(report.totals.failed, 0, "{:?}", report.totals);
    let file = directory.path().join("expire").join("art").join("501.jpg");
    assert!(file.is_file(), "the media was not published");
    assert_eq!(std::fs::read(&file).unwrap(), b"fresh image");
}

#[tokio::test]
async fn the_pin_url_follows_the_origin_of_the_board() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let cache_dir = directory.path().join("cache");
    let mut options = options(directory.path());
    options.download.metadata_cache = true;
    options.download.cache_dir = Some(cache_dir.clone());

    run_target(
        &format!("{}/snapshot/art/", server.url),
        options,
        operation(),
    )
    .await
    .unwrap();

    // The key of the cache is the URL of the pin under the origin of the
    // board, the same key the Python tool writes.
    let stored: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(cache_dir.join(".pinterest_cache.json")).unwrap(),
    )
    .unwrap();
    let keys: Vec<&String> = stored.as_object().unwrap().keys().collect();
    assert_eq!(keys.len(), 1, "{stored}");
    assert_eq!(keys[0], &format!("{}/pin/101/", server.url));
}
