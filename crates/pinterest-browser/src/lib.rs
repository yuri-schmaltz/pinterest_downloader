//! Browser lifecycle and raw snapshots. No Pinterest parsing or UI logic.

use base64::Engine;
use chromiumoxide::{
    browser::{Browser, BrowserConfig},
    cdp::browser_protocol::network::{
        EnableParams, EventLoadingFinished, EventResponseReceived, GetResponseBodyParams,
    },
    Page,
};
use futures::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{HashMap, HashSet},
    future::Future,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use tokio::{sync::Mutex, task::JoinHandle};
use tokio_util::sync::CancellationToken;

#[derive(Debug, thiserror::Error)]
pub enum BrowserError {
    #[error("Chromium não encontrado. Configure --browser-executable ou PINTEREST_CHROMIUM; instale Chromium/Chrome e confira o caminho.")]
    MissingExecutable,
    #[error("Chromium/CDP: {0}")]
    Protocol(String),
    #[error("Tempo limite do browser excedido")]
    Timeout,
    #[error("Operação cancelada")]
    Cancelled,
    #[error("Falha no diretório da sessão: {0}")]
    Io(#[from] std::io::Error),
}
pub type Result<T> = std::result::Result<T, BrowserError>;

#[derive(Debug, Clone)]
pub struct BrowserOptions {
    pub executable: Option<PathBuf>,
    pub headless: bool,
    pub no_sandbox: bool,
    pub operation_timeout: Duration,
    pub user_data_dir: Option<PathBuf>,
}
impl Default for BrowserOptions {
    fn default() -> Self {
        Self {
            executable: None,
            headless: true,
            no_sandbox: false,
            operation_timeout: Duration::from_secs(30),
            user_data_dir: None,
        }
    }
}

/// Explicit path takes precedence over the environment and known installations.
/// An invalid explicit path is an error, never a fallback to a different browser.
pub fn discover_executable(explicit: Option<&Path>) -> Result<PathBuf> {
    if let Some(path) = explicit {
        return path
            .is_file()
            .then(|| path.to_owned())
            .ok_or(BrowserError::MissingExecutable);
    }
    if let Some(path) = std::env::var_os("PINTEREST_CHROMIUM") {
        let path = PathBuf::from(path);
        return path
            .is_file()
            .then_some(path)
            .ok_or(BrowserError::MissingExecutable);
    }
    if let Ok(path) = chromiumoxide::detection::default_executable(Default::default()) {
        if path.is_file() {
            return Ok(path);
        }
    }
    // Reuse an existing Playwright installation without requiring Python/Node.
    let cache = std::env::var_os("PLAYWRIGHT_BROWSERS_PATH")
        .map(PathBuf::from)
        .or_else(|| {
            if cfg!(target_os = "windows") {
                std::env::var_os("LOCALAPPDATA").map(|p| PathBuf::from(p).join("ms-playwright"))
            } else if cfg!(target_os = "macos") {
                std::env::var_os("HOME")
                    .map(|p| PathBuf::from(p).join("Library/Caches/ms-playwright"))
            } else {
                std::env::var_os("XDG_CACHE_HOME")
                    .map(PathBuf::from)
                    .or_else(|| std::env::var_os("HOME").map(|p| PathBuf::from(p).join(".cache")))
                    .map(|p| p.join("ms-playwright"))
            }
        });
    if let Some(cache) = cache {
        if let Ok(entries) = std::fs::read_dir(cache) {
            let mut paths: Vec<_> = entries.flatten().map(|e| e.path()).collect();
            paths.sort();
            for path in paths.into_iter().rev() {
                if !path
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .starts_with("chromium-")
                {
                    continue;
                }
                for binary in ["chrome-linux64/chrome", "chrome-linux/chrome", "chrome-win64/chrome.exe", "chrome-win/chrome.exe", "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing", "chrome-mac/Chromium.app/Contents/MacOS/Chromium"] {
                    let candidate = path.join(binary);
                    if candidate.is_file() { return Ok(candidate); }
                }
            }
        }
    }
    Err(BrowserError::MissingExecutable)
}

pub struct BrowserSession {
    browser: Browser,
    handler: JoinHandle<()>,
    _temporary_profile: Option<tempfile::TempDir>,
    options: BrowserOptions,
    cancel: CancellationToken,
    process_id: Option<u32>,
}

impl BrowserSession {
    pub async fn launch(options: BrowserOptions, cancel: CancellationToken) -> Result<Self> {
        let executable = discover_executable(options.executable.as_deref())?;
        let temporary = if options.user_data_dir.is_none() {
            Some(tempfile::tempdir()?)
        } else {
            None
        };
        let profile = options
            .user_data_dir
            .as_deref()
            .unwrap_or_else(|| temporary.as_ref().unwrap().path());
        let mut config = BrowserConfig::builder()
            .chrome_executable(executable)
            .user_data_dir(profile)
            .respect_https_errors()
            .launch_timeout(options.operation_timeout)
            .request_timeout(options.operation_timeout)
            .arg("--disable-dev-shm-usage");
        if !options.headless {
            config = config.with_head();
        }
        if options.no_sandbox {
            config = config.no_sandbox();
        }
        let config = config.build().map_err(BrowserError::Protocol)?;
        let (mut browser, mut events) =
            guarded(&cancel, options.operation_timeout, Browser::launch(config)).await?;
        // The pid is read once, right after the launch: the child handle is
        // only reachable through a mutable borrow, and the caller wants to
        // compare the browser of one board with the browser of the next.
        let process_id = browser.get_mut_child().and_then(|child| child.inner.id());
        let handler = tokio::spawn(async move {
            while let Some(event) = events.next().await {
                if event.is_err() {
                    break;
                }
            }
        });
        Ok(Self {
            browser,
            handler,
            _temporary_profile: temporary,
            options,
            cancel,
            process_id,
        })
    }

    /// The pid of the browser process, when it could be read.
    pub fn process_id(&self) -> Option<u32> {
        self.process_id
    }

    pub async fn new_page(&self) -> Result<BrowserPage> {
        let page = guarded(
            &self.cancel,
            self.options.operation_timeout,
            self.browser.new_page("about:blank"),
        )
        .await?;
        BrowserPage::new(page, self.cancel.clone(), self.options.operation_timeout).await
    }

    pub async fn close(mut self) -> Result<()> {
        // Shutdown is independent of cancellation and always reaps our child.
        // The graceful window is generous because a loaded machine can be slow
        // to answer; the forced path below is the backstop.
        let graceful = tokio::time::timeout(Duration::from_secs(10), self.browser.close()).await;
        let mut forced = !matches!(graceful, Ok(Ok(_)));
        if !forced {
            forced = !matches!(
                tokio::time::timeout(Duration::from_secs(1), self.browser.wait()).await,
                Ok(Ok(_))
            );
        }
        if forced {
            match tokio::time::timeout(Duration::from_secs(5), self.browser.kill()).await {
                Ok(Some(Ok(())) | None) => {}
                Ok(Some(Err(error))) => {
                    // The browser may have exited between the wait and the kill.
                    // A process that is already gone was reaped, which is
                    // exactly what this method exists to guarantee, so a failed
                    // kill is not an error in that case.
                    let already_gone = matches!(
                        tokio::time::timeout(Duration::from_secs(1), self.browser.wait()).await,
                        Ok(Ok(Some(_)))
                    );
                    if !already_gone {
                        return Err(BrowserError::Io(error));
                    }
                }
                Err(_) => return Err(BrowserError::Timeout),
            }
        }
        self.handler.abort();
        Ok(())
    }
}
impl Drop for BrowserSession {
    fn drop(&mut self) {
        self.handler.abort();
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkSnapshot {
    pub href: String,
    pub title: String,
    pub thumbnail: String,
    #[serde(default)]
    pub recommendation: bool,
    /// The container of the page the link came from, given by its
    /// `data-test-id` or `data-parity`. It tells a pin of the board apart
    /// from a pin that Pinterest recommends next to it.
    #[serde(default)]
    pub origin: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkPayload {
    pub url: String,
    pub body: Value,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageSnapshot {
    pub url: String,
    pub html: String,
    pub links: Vec<LinkSnapshot>,
    pub height: u64,
    pub at_bottom: bool,
    pub end_of_feed: bool,
    /// Whether the document finished parsing. A page that is still loading can
    /// look identical to an empty one, so this decides when it is safe to
    /// conclude that nothing changed.
    pub document_ready: bool,
    pub login_required: bool,
    /// The page shows the pins of the board only as a blurred preview.
    ///
    /// A visitor without a session sees the pins blocked and the feed
    /// empty. Reporting that as "the board is empty" would be a wrong
    /// answer: the board has pins, the visitor just cannot see them.
    pub gated: bool,
    pub network: Vec<NetworkPayload>,
    pub network_truncated: bool,
    pub pending_requests: usize,
}
#[derive(Default)]
struct NetworkLog {
    entries: Vec<NetworkPayload>,
    bytes: usize,
    truncated: bool,
    pending: usize,
}

pub struct BrowserPage {
    page: Page,
    capture: JoinHandle<()>,
    network: Arc<Mutex<NetworkLog>>,
    cancel: CancellationToken,
    timeout: Duration,
}

impl BrowserPage {
    async fn new(page: Page, cancel: CancellationToken, timeout: Duration) -> Result<Self> {
        let mut responses = guarded(
            &cancel,
            timeout,
            page.event_listener::<EventResponseReceived>(),
        )
        .await?;
        let mut finished = guarded(
            &cancel,
            timeout,
            page.event_listener::<EventLoadingFinished>(),
        )
        .await?;
        guarded(
            &cancel,
            timeout,
            page.execute(
                EnableParams::builder()
                    .max_total_buffer_size(8 * 1024 * 1024)
                    .max_resource_buffer_size(2 * 1024 * 1024)
                    .build(),
            ),
        )
        .await?;
        let network = Arc::new(Mutex::new(NetworkLog::default()));
        let captured = network.clone();
        let capture_page = page.clone();
        let stop = cancel.clone();
        let capture = tokio::spawn(async move {
            let mut pending = HashMap::new();
            let mut loaded = HashSet::new();
            loop {
                tokio::select! {
                    _ = stop.cancelled() => break,
                    response = responses.next() => {
                        let Some(response) = response else { break; };
                        let mime = response.response.mime_type.to_ascii_lowercase();
                        if mime.contains("json") {
                            pending.insert(response.request_id.clone(), response.response.url.clone());
                            // Count the request as in flight as soon as its headers
                            // arrive, so a caller that is still waiting for the
                            // payload knows the content is not final yet.
                            captured.lock().await.pending = pending.len();
                        }
                    },
                    response = finished.next() => {
                        let Some(response) = response else { break; };
                        loaded.insert(response.request_id.clone());
                    },
                }
                let ready: Vec<_> = pending
                    .keys()
                    .filter(|id| loaded.contains(*id))
                    .cloned()
                    .collect();
                for request in ready {
                    let url = pending.remove(&request).unwrap();
                    loaded.remove(&request);
                    captured.lock().await.pending = pending.len() + 1;
                    if let Ok(body) = guarded(
                        &stop,
                        timeout,
                        capture_page.execute(GetResponseBodyParams::new(request)),
                    )
                    .await
                    {
                        let body = body.result;
                        let data = if body.base64_encoded {
                            match base64::engine::general_purpose::STANDARD.decode(&body.body) {
                                Ok(data) => data,
                                Err(_) => continue,
                            }
                        } else {
                            body.body.into_bytes()
                        };
                        let mut log = captured.lock().await;
                        if data.len() > 2 * 1024 * 1024
                            || log.bytes + data.len() > 8 * 1024 * 1024
                            || log.entries.len() >= 256
                        {
                            log.truncated = true;
                            continue;
                        }
                        if let Ok(json) = serde_json::from_slice(&data) {
                            log.bytes += data.len();
                            log.entries.push(NetworkPayload { url, body: json });
                        }
                    } else {
                        captured.lock().await.truncated = true;
                    }
                }
                captured.lock().await.pending = pending.len();
                if pending.len() > 512 || loaded.len() > 2048 {
                    pending.clear();
                    loaded.clear();
                    captured.lock().await.truncated = true;
                }
            }
        });
        Ok(Self {
            page,
            capture,
            network,
            cancel,
            timeout,
        })
    }

    pub async fn navigate(&self, url: &str) -> Result<()> {
        guarded(&self.cancel, self.timeout, self.page.goto(url)).await?;
        Ok(())
    }
    pub async fn evaluate(&self, expression: &str) -> Result<Value> {
        let result = guarded(&self.cancel, self.timeout, self.page.evaluate(expression)).await?;
        // CDP represents undefined/null without a value field.
        Ok(result.value().cloned().unwrap_or(Value::Null))
    }
    pub async fn snapshot(&self) -> Result<PageSnapshot> {
        let value = self.evaluate(r#"(() => {
            const root = document.scrollingElement || document.documentElement;
            // A recommendation can hide under many names. The board of the
            // user is the only thing that belongs to the board, so anything
            // that says it is a suggestion is left out.
            const recommendationSelector = '[data-test-id*="recommend"], [data-test-id*="related"],'
                + ' [data-test-id*="more-like"], [data-test-id*="morelike"], [data-test-id*="suggest"],'
                + ' [data-parity*="recommend"], [data-parity*="related"], [data-parity*="suggest"],'
                + ' [aria-label*="recommend" i], [aria-label*="more like this" i]';
            return {url: location.href, html: document.documentElement.outerHTML,
                links: Array.from(document.querySelectorAll('a[href]')).slice(0,10000).map(a => {
                    const container = a.closest('[data-test-id], [data-parity]');
                    return {
                    href: a.href, title: (a.getAttribute('title') || a.textContent || '').trim(),
                    thumbnail: a.querySelector('img')?.src || '',
                    recommendation: Boolean(a.closest(recommendationSelector)),
                    origin: container ? (container.getAttribute('data-test-id')
                        || container.getAttribute('data-parity') || '') : ''};
                }),
                end_of_feed: Boolean(document.querySelector('[data-test-id="board-feed-end"]')),
                document_ready: document.readyState !== 'loading',
                login_required: /\/(login|signup)\/?$/.test(location.pathname) || Boolean(document.querySelector('[data-test-id="login-form"], form[action*="/login/"]')),
                gated: Boolean(document.querySelector('[data-test-id="gated-pin-rep"], [data-test-id="gated-pin-image"]')),
                height: Math.ceil(root.scrollHeight), at_bottom: root.scrollTop + innerHeight >= root.scrollHeight - 20};
        })()"#).await?;
        let mut log = self.network.lock().await;
        let entries = std::mem::take(&mut log.entries);
        log.bytes = 0;
        let truncated = std::mem::take(&mut log.truncated);
        let pending_requests = log.pending;
        Ok(PageSnapshot {
            url: value["url"].as_str().unwrap_or_default().to_owned(),
            html: value["html"].as_str().unwrap_or_default().to_owned(),
            links: serde_json::from_value(value["links"].clone())
                .map_err(|error| BrowserError::Protocol(error.to_string()))?,
            height: value["height"].as_u64().unwrap_or_default(),
            at_bottom: value["at_bottom"].as_bool().unwrap_or(false),
            end_of_feed: value["end_of_feed"].as_bool().unwrap_or(false),
            document_ready: value["document_ready"].as_bool().unwrap_or(false),
            login_required: value["login_required"].as_bool().unwrap_or(false),
            gated: value["gated"].as_bool().unwrap_or(false),
            network: entries,
            network_truncated: truncated,
            pending_requests,
        })
    }
    pub async fn scroll(&self) -> Result<()> {
        self.evaluate("window.scrollBy(0, Math.max(innerHeight * 0.8, 600)); null")
            .await?;
        Ok(())
    }
    pub async fn cookies(&self) -> Result<Vec<Value>> {
        let cookies = guarded(&self.cancel, self.timeout, self.page.get_cookies()).await?;
        cookies
            .into_iter()
            .map(|cookie| {
                serde_json::to_value(cookie)
                    .map_err(|error| BrowserError::Protocol(error.to_string()))
            })
            .collect()
    }
    pub async fn close(self) -> Result<()> {
        self.capture.abort();
        guarded(&self.cancel, self.timeout, self.page.clone().close()).await?;
        Ok(())
    }
}
impl Drop for BrowserPage {
    fn drop(&mut self) {
        self.capture.abort();
    }
}

async fn guarded<T, E: std::fmt::Display>(
    cancel: &CancellationToken,
    timeout: Duration,
    future: impl Future<Output = std::result::Result<T, E>>,
) -> Result<T> {
    tokio::select! {
        biased;
        _ = cancel.cancelled() => Err(BrowserError::Cancelled),
        result = tokio::time::timeout(timeout, future) => match result {
            Ok(result) => result.map_err(|error| BrowserError::Protocol(error.to_string())),
            Err(_) => Err(BrowserError::Timeout),
        }
    }
}
