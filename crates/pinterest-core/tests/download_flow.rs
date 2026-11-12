use pinterest_core::{DownloadOptions, Downloader};
use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
};

struct Server {
    base: String,
    hits: Arc<AtomicUsize>,
    task: JoinHandle<()>,
}
impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

async fn server() -> Server {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let address = base.clone();
    let hits = Arc::new(AtomicUsize::new(0));
    let counter = hits.clone();
    let task = tokio::spawn(async move {
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut request = [0u8; 4096];
            let size = socket.read(&mut request).await.unwrap();
            let request = String::from_utf8_lossy(&request[..size]);
            let path = request.split_whitespace().nth(1).unwrap_or("/");
            let (body, content_type, length) = match path {
                "/alice/" => ("<script id='__PWS_DATA__'>{\"boards\":[{\"name\":\"Art\",\"url\":\"/alice/art/\",\"pin_count\":2}]}</script>".to_owned(), "text/html", None),
                "/alice/art/" => (format!(r#"<script id="__PWS_DATA__">{{"pins":[{{"id":"1","images":{{"orig":{{"url":"{address}/media"}}}}}},{{"id":"2","images":{{"orig":{{"url":"{address}/media"}}}}}}]}}</script>"#), "text/html", None),
                "/broken" => ("partial".to_owned(), "image/jpeg", Some(100000)),
                "/empty" => (String::new(), "image/jpeg", None),
                "/media" => { counter.fetch_add(1, Ordering::SeqCst); ("complete image".to_owned(), "image/jpeg", None) },
                _ => ("<html>login or empty board</html>".to_owned(), "text/html", None),
            };
            let response = format!("HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", length.unwrap_or(body.len()));
            socket.write_all(response.as_bytes()).await.unwrap();
        }
    });
    Server { base, hits, task }
}

#[tokio::test]
async fn profile_collects_boards_and_honors_limit_and_cache_options() {
    let server = server().await;
    let directory = tempfile::tempdir().unwrap();
    let options = DownloadOptions {
        out_root: directory.path().to_owned(),
        max_pins: Some(1),
        rate_limiting: false,
        ..Default::default()
    };
    let downloader = Downloader::new().unwrap();
    for _ in 0..2 {
        let results = downloader
            .download_target(&format!("{}/alice/", server.base), &options)
            .await
            .unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!((results[0].downloaded, results[0].total), (1, 1));
        assert_eq!(
            tokio::fs::read(results[0].output_dir.join("1.jpg"))
                .await
                .unwrap(),
            b"complete image"
        );
    }
    assert_eq!(server.hits.load(Ordering::SeqCst), 1);
    let options = DownloadOptions {
        use_cache: false,
        ..options
    };
    downloader
        .download_target(&format!("{}/alice/art/", server.base), &options)
        .await
        .unwrap();
    assert_eq!(server.hits.load(Ordering::SeqCst), 2);
}

#[tokio::test]
async fn broken_and_empty_streams_do_not_publish_files() {
    let server = server().await;
    let directory = tempfile::tempdir().unwrap();
    let downloader = Downloader::new().unwrap();
    for path in ["broken", "empty"] {
        assert!(downloader
            .download_media(
                &format!("{}/{path}", server.base),
                directory.path(),
                Some("42"),
                0
            )
            .await
            .is_err());
        assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 0);
    }
}

#[tokio::test]
async fn zero_workers_and_empty_extraction_are_errors() {
    let server = server().await;
    let downloader = Downloader::new().unwrap();
    let options = DownloadOptions {
        workers: 0,
        ..Default::default()
    };
    assert!(downloader
        .download_board_images(
            "https://www.pinterest.com/alice/art/",
            HashMap::new(),
            &options
        )
        .await
        .is_err());
    assert!(downloader
        .download_target(
            &format!("{}/alice/empty/", server.base),
            &DownloadOptions::default()
        )
        .await
        .is_err());
}

#[tokio::test]
async fn partial_files_and_prefix_collisions_are_not_cache_hits() {
    let server = server().await;
    let directory = tempfile::tempdir().unwrap();
    std::fs::write(directory.path().join("420.jpg"), b"other pin").unwrap();
    std::fs::write(directory.path().join("42.jpg.part"), b"partial").unwrap();
    let path = Downloader::new()
        .unwrap()
        .download_media(
            &format!("{}/media", server.base),
            directory.path(),
            Some("42"),
            0,
        )
        .await
        .unwrap();
    assert_eq!(path.file_name().unwrap(), "42.jpg");
    assert_eq!(std::fs::read(path).unwrap(), b"complete image");
    assert_eq!(server.hits.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn disabling_rate_limit_bypasses_the_token_bucket() {
    let server = server().await;
    let directory = tempfile::tempdir().unwrap();
    let downloader = Downloader::new().unwrap();
    let options = DownloadOptions {
        out_root: directory.path().to_owned(),
        use_cache: false,
        rate_limiting: false,
        max_pins: Some(1),
        ..Default::default()
    };
    // Forty requests exceed the default 15-token burst. The limiter must be
    // consulted when it is enabled and skipped entirely when it is not. The
    // assertion is on the limiter itself, not on wall-clock timing, so a
    // loaded machine cannot make this test fail.
    for _ in 0..20 {
        downloader
            .download_target(&format!("{}/alice/art/", server.base), &options)
            .await
            .unwrap();
    }
    assert_eq!(server.hits.load(Ordering::SeqCst), 20);
    assert_eq!(
        downloader.limiter_waits(),
        0,
        "--no-rate-limit must not wait for tokens"
    );

    // The same traffic with the limiter enabled has to wait for the bucket to
    // refill, which is observable as at least one wait.
    let limited = Downloader::new().unwrap();
    let limited_options = DownloadOptions {
        rate_limiting: true,
        ..options
    };
    for _ in 0..20 {
        limited
            .download_target(&format!("{}/alice/art/", server.base), &limited_options)
            .await
            .unwrap();
    }
    assert!(
        limited.limiter_waits() > 0,
        "the enabled rate limiter never waited for a token"
    );
}
