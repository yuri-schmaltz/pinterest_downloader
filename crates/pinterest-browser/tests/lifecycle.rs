use pinterest_browser::{BrowserError, BrowserOptions, BrowserSession};
use std::time::Duration;
use tokio_util::sync::CancellationToken;

#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;
use fixture::serve;

#[tokio::test]
async fn missing_explicit_executable_is_actionable() {
    let options = BrowserOptions {
        executable: Some("/not/a/browser".into()),
        ..Default::default()
    };
    let result = BrowserSession::launch(options, CancellationToken::new()).await;
    assert!(matches!(result, Err(BrowserError::MissingExecutable)));
}

#[tokio::test]
#[ignore = "requires Chromium; run explicitly or via browser CI job"]
async fn captures_dynamic_json_reuses_session_and_reaps_browser() {
    let server = serve().await;
    let expected: serde_json::Value =
        serde_json::from_str(include_str!("../../../tests/fixtures/parity/expected.json")).unwrap();
    for _ in 0..2 {
        let mut browser = BrowserSession::launch(
            BrowserOptions {
                no_sandbox: true,
                ..Default::default()
            },
            CancellationToken::new(),
        )
        .await
        .unwrap();
        let pid = browser.process_id().unwrap();
        let page = browser.new_page().await.unwrap();
        page.navigate(&format!("{}/alice/art/", server.url))
            .await
            .unwrap();
        let mut ids = Vec::new();
        tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                let snapshot = page.snapshot().await.unwrap();
                for payload in snapshot.network {
                    let id = payload.body["resource_response"]["data"][0]["id"]
                        .as_str()
                        .unwrap()
                        .to_owned();
                    ids.push(id);
                }
                if ids.iter().any(|id| id == "101") {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
        })
        .await
        .unwrap();
        page.scroll().await.unwrap();
        tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                let snapshot = page.snapshot().await.unwrap();
                for payload in snapshot.network {
                    ids.push(
                        payload.body["resource_response"]["data"][0]["id"]
                            .as_str()
                            .unwrap()
                            .to_owned(),
                    );
                }
                if ids.iter().any(|id| id == "102") {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
        })
        .await
        .unwrap();
        ids.sort();
        ids.dedup();
        assert_eq!(serde_json::json!(ids), expected["dynamic_board"]["pin_ids"]);
        assert_eq!(
            page.evaluate("document.querySelectorAll('#pins a').length")
                .await
                .unwrap(),
            1
        );
        assert!(!page.cookies().await.unwrap().is_empty());
        page.close().await.unwrap();
        let second = browser.new_page().await.unwrap();
        second
            .navigate(&format!("{}/session/check", server.url))
            .await
            .unwrap();
        assert!(second
            .evaluate("document.cookie")
            .await
            .unwrap()
            .as_str()
            .unwrap()
            .contains("fixture_cookie=ok"));
        second.close().await.unwrap();
        browser.close().await.unwrap();
        #[cfg(target_os = "linux")]
        assert!(
            !std::path::Path::new(&format!("/proc/{pid}")).exists(),
            "browser process was not reaped"
        );
        #[cfg(not(target_os = "linux"))]
        let _ = pid;
    }
}

#[tokio::test]
#[ignore = "requires Chromium; run explicitly or via browser CI job"]
async fn cancellation_interrupts_javascript_and_still_closes_browser() {
    let cancel = CancellationToken::new();
    let mut browser = BrowserSession::launch(
        BrowserOptions {
            no_sandbox: true,
            ..Default::default()
        },
        cancel.clone(),
    )
    .await
    .unwrap();
    let pid = browser.process_id().unwrap();
    let page = browser.new_page().await.unwrap();
    let cloned = cancel.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(100)).await;
        cloned.cancel();
    });
    let result = tokio::time::timeout(
        Duration::from_secs(2),
        page.evaluate("new Promise(() => {})"),
    )
    .await
    .unwrap();
    assert!(matches!(result, Err(BrowserError::Cancelled)));
    drop(page);
    browser.close().await.unwrap();
    #[cfg(target_os = "linux")]
    assert!(!std::path::Path::new(&format!("/proc/{pid}")).exists());
    #[cfg(not(target_os = "linux"))]
    let _ = pid;
}
