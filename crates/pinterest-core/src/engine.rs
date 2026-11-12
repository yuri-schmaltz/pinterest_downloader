//! Shared operation runner for native presentation layers.

use crate::{
    adaptive::AdaptiveController,
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
use std::future::Future;
use std::sync::Arc;
use std::time::Instant;
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
    if options.download.workers == 0
        || options.download.boards_workers == 0
        || options.download.max_pins == Some(0)
    {
        return Err(PinterestError::Extraction(
            "Workers, quadros em paralelo e limite devem ser positivos".into(),
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
    let cancellation = operation.cancellation();
    let browser_mode = options.mode != CollectionMode::Http;

    // Discovery: which boards does the target contain?
    let (targets, inherited) = if browser_mode {
        let collector = Collector::launch(options.collection.clone(), operation.clone()).await?;
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
        (targets, Some(collector))
    } else {
        // No HTTP fast path in Auto yet: embedded pins alone cannot prove completeness.
        let downloader = Downloader::new()?;
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
                    targets.push(next.to_string());
                }
            }
            targets
        } else {
            vec![url.to_string()]
        };
        (targets, None)
    };

    // The browser path collects the boards in a sorted map, while the HTTP
    // path reads them from a hash map. Sorting here gives both the same
    // stable order, so the report does not shuffle between runs.
    let mut targets = targets;
    targets.sort();

    let discovery_completeness = if parts.len() == 1 {
        Completeness::Unknown
    } else {
        Completeness::Complete
    };

    // Process the boards. Each worker owns its own browser and its own HTTP
    // client, so the session of one board never reaches another. The first
    // worker inherits the browser used for the discovery instead of opening
    // a second one.
    let workers = options
        .download
        .boards_workers
        .max(1)
        .min(targets.len().max(1));
    let queue = Arc::new(tokio::sync::Mutex::new(targets.into_iter().enumerate()));
    let mut slots: Vec<Option<Collector>> = Vec::with_capacity(workers);
    slots.push(inherited);
    for _ in 1..workers {
        slots.push(None);
    }

    let work = async {
        let mut workers_stream = stream::iter(slots.into_iter().map(|slot| {
            let options = options.clone();
            let operation = operation.clone();
            let queue = Arc::clone(&queue);
            async move {
                let mut collector = match slot {
                    Some(collector) => Some(collector),
                    None if browser_mode => Some(
                        Collector::launch(options.collection.clone(), operation.clone()).await?,
                    ),
                    None => None,
                };
                let downloader = Downloader::new()?;
                let mut reports = Vec::new();
                loop {
                    operation.check_cancelled()?;
                    let next = { queue.lock().await.next() };
                    let Some((index, target)) = next else { break };
                    operation
                        .emit(
                            RunEvent::BoardStarted {
                                board_url: target.clone(),
                            },
                            Some(&target),
                            None,
                        )
                        .await;
                    let board = match collector.as_mut() {
                        Some(collector) => collector.collect_board(&target).await?,
                        None => collect_http_board(&downloader, &target, &options.download).await?,
                    };
                    downloader.import_browser_cookies(&board.cookies);
                    let report =
                        download_collected(board, &options.download, &downloader, &operation)
                            .await?;
                    reports.push((index, report));
                }
                if let Some(collector) = collector {
                    collector.close().await?;
                }
                Ok::<Vec<(usize, BoardReport)>, PinterestError>(reports)
            }
        }))
        .buffer_unordered(workers);

        let mut batches: Vec<Vec<(usize, BoardReport)>> = Vec::new();
        while let Some(item) = workers_stream.next().await {
            batches.push(item?);
        }

        // Keep the order of the discovered boards, not the order they finished.
        let mut ordered: Vec<(usize, BoardReport)> = batches.into_iter().flatten().collect();
        ordered.sort_by_key(|(index, _)| *index);
        let mut report = RunReport {
            discovery_completeness,
            boards: Vec::with_capacity(ordered.len()),
            totals: RunTotals::default(),
        };
        for (_, board) in ordered {
            add_totals(&mut report.totals, &board.totals);
            report.boards.push(board);
        }
        Ok(report)
    };
    let result = tokio::select! {
        _ = cancellation.cancelled() => Err(PinterestError::Cancelled),
        result = work => result,
    };
    result
}

/// Build a board from a single HTTP snapshot.
///
/// The snapshot carries the pins that are embedded in the page. It cannot
/// prove that the board is complete, so the completeness stays unknown.
async fn collect_http_board(
    downloader: &Downloader,
    target: &str,
    options: &DownloadOptions,
) -> Result<CollectedBoard> {
    let url = Url::parse(&normalize_url(target))
        .map_err(|_| PinterestError::InvalidUrl(target.to_string()))?;
    let html = downloader
        .fetch_html(url.as_str(), options.rate_limiting)
        .await?;
    let pins: BTreeMap<_, _> = extract_pws_metadata_from_html(&html)
        .into_values()
        .map(|mut pin| {
            if let Ok(image_url) = url.join(&pin.image_url) {
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
    Ok(CollectedBoard {
        board_url: url.to_string(),
        pins,
        pin_links,
        reason: CompletionReason::Snapshot,
        completeness: Completeness::Unknown,
        cookies: Vec::new(),
    })
}

/// The adaptive controller for a phase, when the option asks for one.
///
/// The range mirrors the Python manager: at most the configured number of
/// workers, and at least four of them.
fn adaptive_controller(options: &DownloadOptions) -> Option<Arc<AdaptiveController>> {
    if !options.adaptive {
        return None;
    }
    let max_workers = options.workers.max(1);
    Some(Arc::new(AdaptiveController::new(
        crate::adaptive::AdaptiveConfig {
            min_workers: 4.min(max_workers),
            max_workers,
            ..Default::default()
        },
    )))
}

/// Runs the tasks with a window that the adaptive controller can move.
///
/// The window is the number of tasks in flight. Raising it starts work
/// sooner; lowering it stops new work from starting until the running
/// tasks drain. Work that is already running is never interrupted, because
/// a download that is half done is worth more than one that was thrown
/// away. Without a controller the window stays where it was.
async fn run_dynamic<T, O, F, Fut, S>(
    items: Vec<T>,
    initial: usize,
    controller: Option<Arc<AdaptiveController>>,
    success: S,
    mut task: F,
) -> Vec<Result<O>>
where
    F: FnMut(T) -> Fut,
    Fut: Future<Output = Result<O>>,
    S: Fn(&Result<O>) -> bool,
{
    let mut pending = futures::stream::FuturesUnordered::new();
    let mut iter = items.into_iter();
    let mut results: Vec<Result<O>> = Vec::with_capacity(initial);
    // With a controller the window starts where the controller says, which
    // is the conservative minimum. Without one it stays at the configured
    // number of workers.
    let mut limit = match &controller {
        Some(controller) => controller.current_workers().await.max(1),
        None => initial.max(1),
    };
    let mut completed = 0usize;

    loop {
        while pending.len() < limit {
            let Some(item) = iter.next() else { break };
            let future = task(item);
            pending.push(async move {
                let started = Instant::now();
                let value = future.await;
                (value, started.elapsed())
            });
        }
        let Some((value, elapsed)) = pending.next().await else {
            break;
        };
        completed += 1;
        if let Some(controller) = &controller {
            controller.record(elapsed, success(&value)).await;
            if completed.is_multiple_of(10) {
                controller.adjust().await;
                limit = controller.current_workers().await.max(1);
            }
        }
        results.push(value);
    }
    results
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
        PinCache::load(
            &resolve_cache_dir(options.cache_dir.as_deref()),
            options.cache_ttl,
        )
    } else {
        PinCache::disabled()
    }));
    let cache_enabled = options.metadata_cache;
    let resolution_controller = adaptive_controller(options);
    let resolutions = run_dynamic(
        unresolved,
        options.workers,
        resolution_controller,
        |result| matches!(result, Ok(Some(_))),
        |(id, link)| {
            let cache = Arc::clone(&cache);
            let downloader = &downloader;
            let options = &options;
            async move {
                if cache_enabled {
                    let cached = cache.lock().await.get(&link).map(str::to_string);
                    if let Some(cached) = cached {
                        return Ok(Some(crate::PinMetadata {
                            id,
                            url: link,
                            image_url: cached,
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
        },
    )
    .await;
    for result in resolutions {
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
    if cache_enabled {
        // Every pin whose media URL is known belongs in the cache, including
        // the ones that came with the board snapshot. Without this the
        // cache would stay empty whenever the pins arrive with their media
        // URL already attached.
        {
            let mut guard = cache.lock().await;
            for pin in board.pins.values() {
                if !pin.url.is_empty() && !pin.image_url.is_empty() {
                    guard.insert(&pin.url, &pin.image_url);
                }
            }
        }
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
    let download_controller = adaptive_controller(options);
    let pending = run_dynamic(
        board.pins.into_values().collect::<Vec<_>>(),
        options.workers,
        download_controller,
        |result: &Result<crate::downloader::MediaDownload>| result.is_ok(),
        |pin| {
            let out_dir = &out_dir;
            async move {
                downloader
                    .download_pin(&pin.image_url, out_dir, &pin.id, options)
                    .await
            }
        },
    )
    .await;
    for result in pending {
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
