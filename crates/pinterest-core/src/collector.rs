//! Dynamic collection scoped to one operation. Stable scroll is not proof of completion.

use crate::{
    parser::{
        extract_boards_from_html, extract_boards_from_pws, extract_pin_metadata_from_value,
        extract_pws_metadata_from_html,
    },
    runtime::{Completeness, CompletionReason},
    BoardMetadata, Operation, PinMetadata, PinterestError, Result, RunEvent,
};
use pinterest_browser::{BrowserError, BrowserOptions, BrowserSession, PageSnapshot};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeMap, time::Duration};
use tokio::time::Instant;
use url::Url;

#[derive(Debug, Clone)]
pub struct CollectionOptions {
    pub browser: BrowserOptions,
    pub scroll_pause: Duration,
    pub stable_rounds: usize,
    pub max_duration: Duration,
    pub max_pins: Option<usize>,
    pub manual_login: bool,
}
impl Default for CollectionOptions {
    fn default() -> Self {
        Self {
            browser: BrowserOptions::default(),
            scroll_pause: Duration::from_millis(1200),
            stable_rounds: 20,
            max_duration: Duration::from_secs(150),
            max_pins: None,
            manual_login: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CollectedBoard {
    pub board_url: String,
    pub pins: BTreeMap<String, PinMetadata>,
    pub pin_links: BTreeMap<String, String>,
    pub reason: CompletionReason,
    pub completeness: Completeness,
    // Kept in memory only to transfer the session to the HTTP client later.
    #[serde(skip)]
    pub cookies: Vec<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CollectedProfile {
    pub boards: Vec<BoardMetadata>,
    pub reason: CompletionReason,
    pub completeness: Completeness,
}

pub struct Collector {
    session: BrowserSession,
    options: CollectionOptions,
    operation: Operation,
}
impl Collector {
    pub async fn launch(mut options: CollectionOptions, operation: Operation) -> Result<Self> {
        if options.scroll_pause.is_zero()
            || options.stable_rounds == 0
            || options.max_duration.is_zero()
            || options.max_pins == Some(0)
        {
            return Err(PinterestError::Extraction(
                "Pausa, duração, estabilidade e limite devem ser positivos".into(),
            ));
        }
        if options.manual_login {
            options.browser.headless = false;
        }
        let session = BrowserSession::launch(options.browser.clone(), operation.cancellation())
            .await
            .map_err(browser_error)?;
        Ok(Self {
            session,
            options,
            operation,
        })
    }

    pub async fn close(self) -> Result<()> {
        self.session.close().await.map_err(browser_error)
    }

    pub async fn collect_board(&self, board_url: &str) -> Result<CollectedBoard> {
        let target = validated_url(board_url)?;
        let page = self.session.new_page().await.map_err(browser_error)?;
        let outcome = async {
            page.navigate(target.as_str())
                .await
                .map_err(browser_error)?;
            let mut deadline = Instant::now() + self.options.max_duration;
            let cancel = self.operation.cancellation();
            let mut pins = BTreeMap::new();
            let mut links = BTreeMap::new();
            let mut stable = 0;
            let mut previous_count = 0;
            let mut previous_height = 0;
            let mut truncated = false;
            let mut end_seen = false;
            let reason = loop {
                let snapshot = tokio::select! {
                    biased;
                    _ = cancel.cancelled() => return Err(PinterestError::Cancelled),
                    _ = tokio::time::sleep_until(deadline) => break CompletionReason::Timeout,
                    result = page.snapshot() => result.map_err(browser_error)?,
                };
                if snapshot.login_required {
                    if !self.options.manual_login {
                        return Err(PinterestError::AuthenticationRequired(target.to_string()));
                    }
                    self.operation.request_login(target.as_str()).await?;
                    page.navigate(target.as_str())
                        .await
                        .map_err(browser_error)?;
                    deadline = Instant::now() + self.options.max_duration;
                    continue;
                }
                truncated |= snapshot.network_truncated;
                for link in &snapshot.links {
                    if link.recommendation {
                        continue;
                    }
                    if let Ok(url) = target.join(&link.href) {
                        if url.origin() == target.origin() {
                            if let Some(id) = pin_id(&url) {
                                links.entry(id).or_insert_with(|| url.to_string());
                            }
                        }
                    }
                }
                let metadata = board_metadata(&snapshot, &target);
                for pin in metadata.into_values() {
                    links.entry(pin.id.clone()).or_insert_with(|| {
                        target
                            .join(&format!("/pin/{}/", pin.id))
                            .unwrap()
                            .to_string()
                    });
                    pins.insert(pin.id.clone(), pin);
                }
                end_seen |= snapshot.end_of_feed;
                self.operation
                    .emit(
                        RunEvent::CollectionProgress { count: links.len() },
                        Some(board_url),
                        None,
                    )
                    .await;
                if self.options.max_pins.is_some_and(|max| links.len() >= max) {
                    break CompletionReason::RequestedLimit;
                }
                // Require quiet rounds even after an explicit end marker: network body
                // capture may still be queued behind loadingFinished on the CDP stream.
                //
                // A board that has not produced a single link yet has not proven
                // itself stable: the feed may simply not have arrived, and a
                // silent page is exactly what a slow feed looks like. Only an
                // explicit end marker or a board that already yielded pins can
                // end the collection. The same holds while the document is still
                // parsing or a JSON payload is still on its way.
                let provable = end_seen || !links.is_empty();
                if provable
                    && snapshot.document_ready
                    && snapshot.pending_requests == 0
                    && links.len() == previous_count
                    && snapshot.height == previous_height
                {
                    stable += 1;
                } else {
                    stable = 0;
                }
                if stable >= self.options.stable_rounds {
                    break if end_seen && !truncated && snapshot.pending_requests == 0 {
                        CompletionReason::EndOfFeed
                    } else {
                        CompletionReason::Stable
                    };
                }
                previous_count = links.len();
                previous_height = snapshot.height;
                page.scroll().await.map_err(browser_error)?;
                tokio::select! {
                    _ = cancel.cancelled() => return Err(PinterestError::Cancelled),
                    _ = tokio::time::sleep_until(deadline) => break CompletionReason::Timeout,
                    _ = tokio::time::sleep(self.options.scroll_pause) => {},
                }
            };
            if let Some(max) = self.options.max_pins {
                // Stable ordering makes a requested limit reproducible across DOM/network sources.
                links = links.into_iter().take(max).collect();
                pins.retain(|id, _| links.contains_key(id));
            }
            let completeness = completeness(&reason);
            if truncated {
                self.operation
                    .emit(
                        RunEvent::Warning {
                            message:
                                "Captura de rede atingiu o limite; coleta pode estar incompleta"
                                    .into(),
                        },
                        Some(board_url),
                        None,
                    )
                    .await;
            }
            if links.is_empty() && completeness != Completeness::Complete {
                return Err(PinterestError::Extraction(
                    "Nenhum pin encontrado; quadro vazio não foi comprovado".into(),
                ));
            }
            self.operation
                .emit(
                    RunEvent::CollectionFinished {
                        count: links.len(),
                        reason: reason.clone(),
                        completeness: completeness.clone(),
                    },
                    Some(board_url),
                    None,
                )
                .await;
            let cookies = page.cookies().await.map_err(browser_error)?;
            Ok(CollectedBoard {
                board_url: target.to_string(),
                pins,
                pin_links: links,
                reason,
                completeness,
                cookies,
            })
        }
        .await;
        let closed = page.close().await.map_err(browser_error);
        match outcome {
            Err(error) => Err(error),
            Ok(result) => {
                closed?;
                Ok(result)
            }
        }
    }

    pub async fn collect_profile(&self, profile_url: &str) -> Result<CollectedProfile> {
        let target = validated_url(profile_url)?;
        let username = target
            .path_segments()
            .into_iter()
            .flatten()
            .find(|part| !part.is_empty())
            .ok_or_else(|| PinterestError::InvalidUrl(profile_url.into()))?;
        let page = self.session.new_page().await.map_err(browser_error)?;
        let outcome = async {
            page.navigate(target.as_str())
                .await
                .map_err(browser_error)?;
            let mut deadline = Instant::now() + self.options.max_duration;
            let cancel = self.operation.cancellation();
            let mut boards = BTreeMap::new();
            let mut previous = (0, 0);
            let mut stable = 0;
            let reason = loop {
                let snapshot = tokio::select! {
                    _ = cancel.cancelled() => return Err(PinterestError::Cancelled),
                    _ = tokio::time::sleep_until(deadline) => break CompletionReason::Timeout,
                    result = page.snapshot() => result.map_err(browser_error)?,
                };
                if snapshot.login_required {
                    if !self.options.manual_login {
                        return Err(PinterestError::AuthenticationRequired(target.to_string()));
                    }
                    self.operation.request_login(target.as_str()).await?;
                    page.navigate(target.as_str())
                        .await
                        .map_err(browser_error)?;
                    deadline = Instant::now() + self.options.max_duration;
                    continue;
                }
                let mut entries = extract_boards_from_html(&snapshot.html, username);
                for payload in &snapshot.network {
                    if same_origin(&target, &payload.url) {
                        entries.extend(extract_boards_from_pws(&payload.body, username));
                    }
                }
                for link in &snapshot.links {
                    if link.recommendation {
                        continue;
                    }
                    let raw = serde_json::json!({"url":link.href,"name":link.title});
                    let mut parsed = extract_boards_from_pws(&raw, username);
                    for board in &mut parsed {
                        board.thumbnail_url.clone_from(&link.thumbnail);
                    }
                    entries.extend(parsed);
                }
                for mut board in entries {
                    if let Ok(url) = target.join(&board.url) {
                        if url.origin() != target.origin() {
                            continue;
                        }
                        board.url = url.to_string();
                        boards
                            .entry(board.url.clone())
                            .and_modify(|existing: &mut BoardMetadata| {
                                if existing.thumbnail_url.is_empty() {
                                    existing.thumbnail_url.clone_from(&board.thumbnail_url);
                                }
                                if existing.pin_count_int.is_none() {
                                    existing.pin_count_int = board.pin_count_int;
                                    existing.pin_count.clone_from(&board.pin_count);
                                }
                            })
                            .or_insert(board);
                    }
                }
                let current = (boards.len(), snapshot.height);
                if current == previous {
                    stable += 1;
                } else {
                    stable = 0;
                }
                if stable >= self.options.stable_rounds {
                    break CompletionReason::Stable;
                }
                previous = current;
                page.scroll().await.map_err(browser_error)?;
                tokio::select! {
                    _ = cancel.cancelled() => return Err(PinterestError::Cancelled),
                    _ = tokio::time::sleep_until(deadline) => break CompletionReason::Timeout,
                    _ = tokio::time::sleep(self.options.scroll_pause) => {},
                }
            };
            if boards.is_empty() {
                return Err(PinterestError::Extraction(
                    "Nenhum quadro identificado no perfil".into(),
                ));
            }
            self.operation
                .emit(
                    RunEvent::BoardsFound {
                        count: boards.len(),
                    },
                    None,
                    None,
                )
                .await;
            Ok(CollectedProfile {
                boards: boards.into_values().collect(),
                completeness: completeness(&reason),
                reason,
            })
        }
        .await;
        let closed = page.close().await.map_err(browser_error);
        match outcome {
            Err(error) => Err(error),
            Ok(result) => {
                closed?;
                Ok(result)
            }
        }
    }
}

fn board_metadata(snapshot: &PageSnapshot, target: &Url) -> BTreeMap<String, PinMetadata> {
    let mut pins = extract_pws_metadata_from_html(&snapshot.html);
    for payload in &snapshot.network {
        if !same_origin(target, &payload.url) {
            continue;
        }
        let lower = payload.url.to_ascii_lowercase();
        if lower.contains("related")
            || lower.contains("recommend")
            || lower.contains("morelikethis")
        {
            continue;
        }
        pins.extend(extract_pin_metadata_from_value(&payload.body));
    }
    pins.into_values()
        .filter_map(|mut pin| {
            let image = target.join(&pin.image_url).ok()?;
            if !matches!(image.scheme(), "http" | "https") {
                return None;
            }
            pin.image_url = image.to_string();
            Some((pin.id.clone(), pin))
        })
        .collect()
}
fn same_origin(target: &Url, raw: &str) -> bool {
    target
        .join(raw)
        .is_ok_and(|url| url.origin() == target.origin())
}
fn pin_id(url: &Url) -> Option<String> {
    let parts: Vec<_> = url
        .path_segments()?
        .filter(|part| !part.is_empty())
        .collect();
    (parts.len() == 2
        && parts[0] == "pin"
        && !parts[1].is_empty()
        && parts[1].bytes().all(|byte| byte.is_ascii_digit()))
    .then(|| parts[1].to_owned())
}
fn validated_url(raw: &str) -> Result<Url> {
    let url = Url::parse(&crate::utils::normalize_url(raw))
        .map_err(|_| PinterestError::InvalidUrl(raw.into()))?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
        return Err(PinterestError::InvalidUrl(raw.into()));
    }
    Ok(url)
}
fn completeness(reason: &CompletionReason) -> Completeness {
    match reason {
        CompletionReason::EndOfFeed => Completeness::Complete,
        CompletionReason::RequestedLimit => Completeness::Limited,
        _ => Completeness::Unknown,
    }
}
fn browser_error(error: BrowserError) -> PinterestError {
    match error {
        BrowserError::Cancelled => PinterestError::Cancelled,
        _ => PinterestError::Browser(error.to_string()),
    }
}
