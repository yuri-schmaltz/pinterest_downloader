//! Shared operation runner for native presentation layers.

use crate::{
    cache::{resolve_cache_dir, PinCache},
    collector::{CollectedBoard, CollectionOptions, Collector},
    parser::{extract_boards_from_html, extract_pws_metadata_from_html},
    runtime::{Completeness, CompletionReason, RunTotals},
    utils::{normalize_url, safe_name},
    DownloadOptions, Downloader, Operation, PinterestError, Result, RunEvent,
};
use futures::{stream, StreamExt};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use url::Url;

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CollectionMode {
    #[default]
    Auto,
    Browser,
    Http,
}

#[derive(Debug, Clone, Default)]
pub struct RunOptions {
    pub download: DownloadOptions,
    pub collection: CollectionOptions,
    pub mode: CollectionMode,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BoardReport {
    pub board_url: String,
    pub output_dir: std::path::PathBuf,
    pub reason: CompletionReason,
    pub completeness: Completeness,
    pub totals: RunTotals,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunReport {
    pub discovery_completeness: Completeness,
    pub boards: Vec<BoardReport>,
    pub totals: RunTotals,
}

/// Always emits one terminal event. Presenters must keep draining the bounded
/// event channel while waiting for the operation to finish, including cancellation.
pub async fn run_target(
    target: &str,
    options: RunOptions,
    operation: Operation,
) -> Result<RunReport> {
    operation
        .emit(
            RunEvent::Started {
                target: redacted_target(target),
            },
            None,
            None,
        )
        .await;
    let result = run_inner(target, options, &operation).await;
    match &result {
        Ok(report) => {
            operation
                .emit(
                    RunEvent::Finished {
                        totals: report.totals.clone(),
                    },
                    None,
                    None,
                )
                .await
        }
        Err(PinterestError::Cancelled) => operation.emit(RunEvent::Cancelled, None, None).await,
        Err(error) => {
            operation
                .emit(
                    RunEvent::Failed {
                        code: error_code(error).into(),
                        message: public_error_message(error),
                    },
                    None,
                    None,
                )
                .await
        }
    }
    result
}

async fn run_inner(
    target: &str,
    mut options: RunOptions,
    operation: &Operation,
) -> Result<RunReport> {
    operation.check_cancelled()?;
    if options.download.workers == 0 || options.download.max_pins == Some(0) {
        return Err(PinterestError::Extraction(
            "Workers e limite devem ser positivos".into(),
        ));
    }
    options.collection.max_pins = options.download.max_pins;
    let url = Url::parse(&normalize_url(target))
        .map_err(|_| PinterestError::InvalidUrl(target.into()))?;
    let parts: Vec<_> = url
        .path_segments()
        .into_iter()
        .flatten()
        .filter(|part| !part.is_empty())
        .collect();
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || parts.is_empty()
        || parts.len() > 2
        || parts[0] == "pin"
    {
        return Err(PinterestError::InvalidUrl(target.into()));
    }
    let downloader = Downloader::new()?;
    let cancellation = operation.cancellation();
    // No HTTP fast path in Auto yet: embedded pins alone cannot prove completeness.
    if options.mode == CollectionMode::Http {
        let work = async {
            let html = downloader
                .fetch_html(url.as_str(), options.download.rate_limiting)
                .await?;
            let targets = if parts.len() == 1 {
                let boards = extract_boards_from_html(&html, parts[0]);
                if boards.is_empty() {
                    return Err(PinterestError::Extraction(
                        "Nenhum quadro no snapshot HTTP; use --mode browser".into(),
                    ));
                }
                let mut targets = Vec::new();
                for board in boards {
                    let next = url
                        .join(&board.url)
                        .map_err(|_| PinterestError::InvalidUrl(board.url.clone()))?;
                    if next.origin() == url.origin() {
                        targets.push(next);
                    }
                }
                targets
            } else {
                vec![url.clone()]
            };
            let mut report = RunReport {
                discovery_completeness: if parts.len() == 1 {
                    Completeness::Unknown
                } else {
                    Completeness::Complete
                },
                boards: Vec::new(),
                totals: RunTotals::default(),
            };
            for target in targets {
                operation
                    .emit(
                        RunEvent::BoardStarted {
                            board_url: target.to_string(),
                        },
                        Some(target.as_str()),
                        None,
                    )
                    .await;
                let board_html = if target == url {
                    html.clone()
                } else {
                    downloader
                        .fetch_html(target.as_str(), options.download.rate_limiting)
                        .await?
                };
                let pins: BTreeMap<_, _> = extract_pws_metadata_from_html(&board_html)
                    .into_values()
                    .map(|mut pin| {
                        if let Ok(image_url) = target.join(&pin.image_url) {
                            pin.image_url = image_url.to_string();
                        }
                        (pin.id.clone(), pin)
                    })
                    .collect();
                if pins.is_empty() {
                    return Err(PinterestError::Extraction(
                        "Nenhum pin no snapshot HTTP".into(),
                    ));
                }
                let pin_links = pins
                    .iter()
                    .map(|(id, pin)| (id.clone(), pin.url.clone()))
                    .collect();
                let board = CollectedBoard {
                    board_url: target.to_string(),
                    pins,
                    pin_links,
                    reason: CompletionReason::Snapshot,
                    completeness: Completeness::Unknown,
                    cookies: Vec::new(),
                };
                let board_report =
                    download_collected(board, &options.download, &downloader, operation).await?;
                add_totals(&mut report.totals, &board_report.totals);
                report.boards.push(board_report);
            }
            Ok(report)
        };
        return tokio::select! { _ = cancellation.cancelled() => Err(PinterestError::Cancelled), result = work => result };
    }
    let collector = Collector::launch(options.collection.clone(), operation.clone()).await?;
    let work = async {
        let targets = if parts.len() == 1 {
            let profile = collector.collect_profile(url.as_str()).await?;
            operation
                .emit(
                    RunEvent::Warning {
                        message: format!(
                            "Descoberta do perfil terminou com {:?}; completude {:?}",
                            profile.reason, profile.completeness
                        ),
                    },
                    None,
                    None,
                )
                .await;
            profile.boards.into_iter().map(|board| board.url).collect()
        } else {
            vec![url.to_string()]
        };
        let mut report = RunReport {
            discovery_completeness: if parts.len() == 1 {
                Completeness::Unknown
            } else {
                Completeness::Complete
            },
            boards: Vec::new(),
            totals: RunTotals::default(),
        };
        for target in targets {
            operation
                .emit(
                    RunEvent::BoardStarted {
                        board_url: target.clone(),
                    },
                    Some(&target),
                    None,
                )
                .await;
            let board = collector.collect_board(&target).await?;
            downloader.import_browser_cookies(&board.cookies);
            let board_report =
                download_collected(board, &options.download, &downloader, operation).await?;
            add_totals(&mut report.totals, &board_report.totals);
            report.boards.push(board_report);
        }
        Ok(report)
    };
    let result = tokio::select! { _ = cancellation.cancelled() => Err(PinterestError::Cancelled), result = work => result };
    let closed = collector.close().await;
    match result {
        Err(error) => Err(error),
        Ok(report) => {
            closed?;
            Ok(report)
        }
    }
}

async fn download_collected(
    mut board: CollectedBoard,
    options: &DownloadOptions,
    downloader: &Downloader,
    operation: &Operation,
) -> Result<BoardReport> {
    if let Some(max) = options.max_pins {
        board.pin_links = board.pin_links.into_iter().take(max).collect();
        board.pins.retain(|id, _| board.pin_links.contains_key(id));
    }
    let url = Url::parse(&board.board_url)
        .map_err(|_| PinterestError::InvalidUrl(board.board_url.clone()))?;
    let parts: Vec<_> = url
        .path_segments()
        .into_iter()
        .flatten()
        .filter(|part| !part.is_empty())
        .collect();
    let out_dir = options.out_root.join(safe_name(&parts.join("_")));
    let unresolved: Vec<_> = board
        .pin_links
        .iter()
        .filter(|(id, _)| !board.pins.contains_key(*id))
        .map(|(id, link)| (id.clone(), link.clone()))
        .collect();
    // The metadata cache short-circuits the network for pins resolved before.
    let cache = Arc::new(Mutex::new(if options.metadata_cache {
        PinCache::load(&resolve_cache_dir(options.cache_dir.as_deref()))
    } else {
        PinCache::disabled()
    }));
    let cache_enabled = options.metadata_cache;
    let mut resolutions = stream::iter(unresolved.into_iter().map(|(id, link)| {
        let cache = Arc::clone(&cache);
        async move {
            if cache_enabled {
                let cached = cache.lock().await.get(&link).map(str::to_string);
                if let Some(media_url) = cached {
                    return Ok(Some(crate::PinMetadata {
                        id,
                        url: link,
                        image_url: media_url,
                        title: String::new(),
                    }));
                }
            }
            let resolved = downloader
                .resolve_pin(&link, &id, options.rate_limiting)
                .await?;
            if cache_enabled {
                if let Some(pin) = &resolved {
                    cache.lock().await.insert(&link, &pin.image_url);
                }
            }
            Ok(resolved)
        }
    }))
    .buffer_unordered(options.workers);
    while let Some(result) = resolutions.next().await {
        operation.check_cancelled()?;
        match result {
            Ok(Some(pin)) => {
                board.pins.insert(pin.id.clone(), pin);
            }
            Ok(None) => {}
            Err(error) => {
                operation
                    .emit(
                        RunEvent::Warning {
                            message: public_error_message(&error),
                        },
                        Some(&board.board_url),
                        None,
                    )
                    .await
            }
        }
        operation
            .emit(
                RunEvent::ResolutionProgress {
                    resolved: board.pins.len(),
                    total: board.pin_links.len(),
                },
                Some(&board.board_url),
                None,
            )
            .await;
    }
    drop(resolutions);
    if cache_enabled {
        // A cache write failure must not fail the run: the downloads already
        // happened and the next run simply resolves the pins again.
        if let Err(error) = cache.lock().await.save().await {
            operation
                .emit(
                    RunEvent::Warning {
                        message: format!("Cache de metadados nao foi gravado: {error}"),
                    },
                    Some(&board.board_url),
                    None,
                )
                .await;
        }
    }
    let mut totals = RunTotals {
        discovered: board.pin_links.len(),
        resolved: board.pins.len(),
        ..Default::default()
    };
    let mut pending = stream::iter(board.pins.into_values().map(|pin| {
        let out_dir = &out_dir;
        async move {
            downloader
                .download_pin(&pin.image_url, out_dir, &pin.id, options)
                .await
        }
    }))
    .buffer_unordered(options.workers);
    while let Some(result) = pending.next().await {
        operation.check_cancelled()?;
        match result {
            Ok(media) => {
                if media.reused {
                    totals.reused += 1;
                } else {
                    totals.downloaded += 1;
                }
                if tokio::fs::metadata(&media.path)
                    .await
                    .is_ok_and(|meta| meta.is_file() && meta.len() > 0)
                {
                    totals.verified += 1;
                } else {
                    totals.failed += 1;
                }
            }
            Err(error) => {
                totals.failed += 1;
                operation
                    .emit(
                        RunEvent::Warning {
                            message: public_error_message(&error),
                        },
                        Some(&board.board_url),
                        None,
                    )
                    .await;
            }
        }
        operation
            .emit(
                RunEvent::DownloadProgress {
                    current: totals.downloaded + totals.reused + totals.failed,
                    total: totals.resolved,
                },
                Some(&board.board_url),
                None,
            )
            .await;
    }
    drop(pending);
    totals.failed += totals.discovered.saturating_sub(totals.resolved);
    if board.completeness == Completeness::Unknown {
        operation.emit(RunEvent::Warning { message: "A coleta terminou sem comprovar o fim do quadro; resultado parcial/desconhecido".into() }, Some(&board.board_url), None).await;
    }
    operation
        .emit(
            RunEvent::BoardFinished {
                totals: totals.clone(),
            },
            Some(&board.board_url),
            None,
        )
        .await;
    Ok(BoardReport {
        board_url: board.board_url,
        output_dir: out_dir,
        reason: board.reason,
        completeness: board.completeness,
        totals,
    })
}
fn add_totals(total: &mut RunTotals, board: &RunTotals) {
    total.discovered += board.discovered;
    total.resolved += board.resolved;
    total.downloaded += board.downloaded;
    total.reused += board.reused;
    total.verified += board.verified;
    total.failed += board.failed;
    total.skipped += board.skipped;
}
pub fn error_code(error: &PinterestError) -> &'static str {
    match error {
        PinterestError::Cancelled => "cancelled",
        PinterestError::Browser(_) => "browser",
        PinterestError::PrivateProfile(_) | PinterestError::AuthenticationRequired(_) => {
            "authentication"
        }
        PinterestError::InvalidUrl(_) => "invalid_target",
        PinterestError::Extraction(_) => "extraction",
        PinterestError::Network(_) => "network",
        PinterestError::Io(_) => "io",
        PinterestError::Serialization(_) => "serialization",
        PinterestError::RateLimited(_) => "rate_limited",
    }
}

pub fn public_error_message(error: &PinterestError) -> String {
    match error {
        PinterestError::Network(error) => {
            if let Some(status) = error.status() {
                format!("Falha HTTP: {status}")
            } else if error.is_timeout() {
                "Tempo limite de rede excedido".into()
            } else {
                "Falha de rede; URL da mídia omitida para preservar credenciais".into()
            }
        }
        _ => error.to_string(),
    }
}
fn redacted_target(raw: &str) -> String {
    if let Ok(mut url) = Url::parse(&normalize_url(raw)) {
        let _ = url.set_username("");
        let _ = url.set_password(None);
        url.set_query(None);
        url.set_fragment(None);
        url.to_string()
    } else {
        "alvo inválido".into()
    }
}
