//! Shared operation runner for native presentation layers.

use crate::{
    adaptive::AdaptiveController,
    cache::{resolve_cache_dir, PinCache},
    collector::{CollectedBoard, CollectionOptions, Collector, FeedOrigin},
    parser::{extract_boards_from_html, extract_pws_metadata_from_html},
    runtime::{Completeness, CompletionReason, RunTotals},
    utils::normalize_url,
    DownloadOptions, Downloader, Operation, PinterestError, Result, RunEvent,
};
use futures::{stream, StreamExt};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::future::Future;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;
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
    /// Where the pins of the board came from and what was left out.
    pub origin: FeedOrigin,
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

/// The boards a target holds, and how much the discovery could prove.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiscoveredBoards {
    pub target: String,
    pub boards: Vec<crate::BoardMetadata>,
    pub completeness: Completeness,
}

/// Discover the boards of a target without downloading anything.
///
/// A graphical interface needs the list before the user chooses what to
/// download. The discovery is the same the run does; only the download is
/// left out.
pub async fn discover_boards(
    target: &str,
    options: RunOptions,
    operation: Operation,
) -> Result<DiscoveredBoards> {
    operation.check_cancelled()?;
    let mut options = options;
    validate_options(&mut options)?;
    let url = validated_target(target)?;
    let parts = url_parts(&url);
    let browser_mode = options.mode != CollectionMode::Http;
    let (boards, completeness) = if browser_mode {
        let collector = Collector::launch(options.collection.clone(), operation.clone()).await?;
        let result = if parts.len() == 1 {
            let profile = collector.collect_profile(url.as_str()).await?;
            (profile.boards, profile.completeness)
        } else {
            (
                vec![crate::BoardMetadata {
                    url: url.to_string(),
                    title: parts.last().cloned().unwrap_or_default(),
                    thumbnail_url: String::new(),
                    pin_count: String::new(),
                    pin_count_int: None,
                }],
                Completeness::Complete,
            )
        };
        collector.close().await?;
        result
    } else {
        let downloader = Downloader::with_cancellation(operation.cancellation())?;
        let html = downloader
            .fetch_html(url.as_str(), options.download.rate_limiting)
            .await?;
        let mut boards = Vec::new();
        if parts.len() == 1 {
            for board in extract_boards_from_html(&html, &parts[0]) {
                if let Ok(next) = url.join(&board.url) {
                    if next.origin() == url.origin() {
                        boards.push(crate::BoardMetadata {
                            url: next.to_string(),
                            ..board
                        });
                    }
                }
            }
        } else {
            boards.push(crate::BoardMetadata {
                url: url.to_string(),
                title: parts.last().cloned().unwrap_or_default(),
                thumbnail_url: String::new(),
                pin_count: String::new(),
                pin_count_int: None,
            });
        }
        (boards, Completeness::Unknown)
    };
    if boards.is_empty() {
        return Err(PinterestError::Extraction(
            "Nenhum quadro encontrado no alvo".into(),
        ));
    }
    Ok(DiscoveredBoards {
        target: url.to_string(),
        boards,
        completeness,
    })
}

/// Download a list of boards, and only those.
///
/// A graphical interface lets the user pick a subset of the boards. The
/// engine downloads exactly the list it receives.
pub async fn run_boards(
    boards: Vec<String>,
    options: RunOptions,
    operation: Operation,
) -> Result<RunReport> {
    operation.check_cancelled()?;
    let mut options = options;
    validate_options(&mut options)?;
    let result = process_boards(boards, Completeness::Complete, options, &operation, None).await;
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

fn validate_options(options: &mut RunOptions) -> Result<()> {
    if options.download.workers == 0
        || options.download.boards_workers == 0
        || options.download.max_pins == Some(0)
    {
        return Err(PinterestError::Extraction(
            "Workers, quadros em paralelo e limite devem ser positivos".into(),
        ));
    }
    options.collection.max_pins = options.download.max_pins;
    Ok(())
}

fn validated_target(target: &str) -> Result<Url> {
    let url = Url::parse(&normalize_url(target))
        .map_err(|_| PinterestError::InvalidUrl(target.into()))?;
    let parts = url_parts(&url);
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || parts.is_empty()
        || parts.len() > 2
        || parts[0] == "pin"
    {
        return Err(PinterestError::InvalidUrl(target.into()));
    }
    Ok(url)
}

fn url_parts(url: &Url) -> Vec<String> {
    url.path_segments()
        .into_iter()
        .flatten()
        .filter(|part| !part.is_empty())
        .map(str::to_owned)
        .collect()
}

async fn run_inner(
    target: &str,
    mut options: RunOptions,
    operation: &Operation,
) -> Result<RunReport> {
    operation.check_cancelled()?;
    validate_options(&mut options)?;
    let url = validated_target(target)?;
    let parts = url_parts(&url);
    let cancellation = operation.cancellation();
    let browser_mode = options.mode != CollectionMode::Http;

    // Discovery: which boards does the target contain?
    let (targets, inherited, profile_completeness) = if browser_mode {
        let collector = Collector::launch(options.collection.clone(), operation.clone()).await?;
        let (targets, profile_completeness) = if parts.len() == 1 {
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
            (
                profile.boards.into_iter().map(|board| board.url).collect(),
                profile.completeness,
            )
        } else {
            (vec![url.to_string()], Completeness::Complete)
        };
        (targets, Some(collector), profile_completeness)
    } else {
        // No HTTP fast path in Auto yet: embedded pins alone cannot prove completeness.
        let downloader = Downloader::with_cancellation(cancellation.clone())?;
        let html = downloader
            .fetch_html(url.as_str(), options.download.rate_limiting)
            .await?;
        let targets = if parts.len() == 1 {
            let boards = extract_boards_from_html(&html, &parts[0]);
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
        (targets, None, Completeness::Unknown)
    };

    // The browser path collects the boards in a sorted map, while the HTTP
    // path reads them from a hash map. Sorting here gives both the same
    // stable order, so the report does not shuffle between runs.
    let mut targets = targets;
    targets.sort();

    // The discovery of a profile is what the profile page could prove. A
    // board is its own discovery, so nothing is missing there.
    let discovery_completeness = if parts.len() == 1 {
        profile_completeness
    } else {
        Completeness::Complete
    };

    process_boards(
        targets,
        discovery_completeness,
        options,
        operation,
        inherited,
    )
    .await
}

/// Download the boards, in parallel, and build the report.
///
/// Each worker owns its own browser and its own HTTP client, so the session
/// of one board never reaches another. The first worker inherits the browser
/// used for the discovery instead of opening a second one.
async fn process_boards(
    targets: Vec<String>,
    discovery_completeness: Completeness,
    options: RunOptions,
    operation: &Operation,
    inherited: Option<Collector>,
) -> Result<RunReport> {
    let cancellation = operation.cancellation();
    let browser_mode = options.mode != CollectionMode::Http;
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
                // The browser is closed on every path, including the error and
                // the cancellation ones. A cancelled run must not leave a
                // browser behind.
                let outcome: Result<Vec<(usize, BoardReport)>> = async {
                    let downloader = Downloader::with_cancellation(operation.cancellation())?;
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
                            None => {
                                collect_http_board(&downloader, &target, &options.download).await?
                            }
                        };
                        downloader.import_browser_cookies(&board.cookies);
                        let report =
                            download_collected(board, &options.download, &downloader, &operation)
                                .await?;
                        reports.push((index, report));
                    }
                    Ok(reports)
                }
                .await;
                let closed = match collector {
                    Some(collector) => collector.close().await,
                    None => Ok(()),
                };
                match (outcome, closed) {
                    (Ok(reports), Ok(())) => Ok(reports),
                    (Err(error), _) => Err(error),
                    (Ok(_), Err(error)) => Err(error),
                }
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
    tokio::pin!(work);
    let result = tokio::select! {
        biased;
        _ = cancellation.cancelled() => {
            // The workers observe the cancellation and close their browsers
            // on the way out. The grace period bounds the wait so that the
            // cancellation is observed in time; when it expires the browser
            // is torn down with the run.
            let _ = tokio::time::timeout(CANCEL_GRACE, &mut work).await;
            Err(PinterestError::Cancelled)
        }
        result = &mut work => result,
    };
    result
}

/// How long the workers may take to unwind after a cancellation.
///
/// The plan asks for the cancellation to be observed in at most two seconds,
/// so the grace period stays below that. A browser that does not answer is
/// torn down with the run.
const CANCEL_GRACE: std::time::Duration = std::time::Duration::from_millis(1200);

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
            // The URL of the pin follows the origin of the board, so that the
            // cache of the HTTP mode is the same as the one of the browser.
            if let Ok(pin_url) = url.join(&format!("/pin/{}/", pin.id)) {
                pin.url = pin_url.to_string();
            }
            (pin.id.clone(), pin)
        })
        .collect();
    if pins.is_empty() {
        return Err(PinterestError::Extraction(
            "Nenhum pin no snapshot HTTP".into(),
        ));
    }
    let pin_links: BTreeMap<String, String> = pins
        .iter()
        .map(|(id, pin)| (id.clone(), pin.url.clone()))
        .collect();
    let pin_count = pin_links.len();
    Ok(CollectedBoard {
        board_url: url.to_string(),
        pins,
        pin_links,
        reason: CompletionReason::Snapshot,
        completeness: Completeness::Unknown,
        origin: FeedOrigin {
            sources: BTreeMap::from([("snapshot".to_string(), pin_count)]),
            excluded_recommendations: 0,
        },
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
    cancel: CancellationToken,
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
        // A cancelled run stops here. Waiting for the tasks that are already
        // running would make the cancellation wait for a network timeout,
        // and the plan asks for it in at most two seconds.
        let next = tokio::select! {
            biased;
            _ = cancel.cancelled() => None,
            next = pending.next() => next,
        };
        let Some((value, elapsed)) = next else {
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
    let cancellation = operation.cancellation();
    let url = Url::parse(&board.board_url)
        .map_err(|_| PinterestError::InvalidUrl(board.board_url.clone()))?;
    let out_dir = crate::utils::board_output_dir(&options.out_root, &url);
    let legacy_dir = crate::utils::legacy_board_output_dir(&options.out_root, &url);
    // An earlier Rust build wrote the board into a single directory named
    // `<user>_<board>`. The Python tool writes `<user>/<board>`. Moving the
    // old directory keeps the files, stops the download of what is already on
    // disk and leaves both tools looking at the same place. When both
    // directories exist the move is skipped: merging them could overwrite a
    // file, and the reuse check below still finds the old files where they
    // are.
    let mut reuse_dirs: Vec<std::path::PathBuf> = Vec::new();
    if legacy_dir != out_dir {
        let legacy_exists = tokio::fs::metadata(&legacy_dir).await.is_ok();
        let current_exists = tokio::fs::metadata(&out_dir).await.is_ok();
        if legacy_exists && !current_exists {
            if let Some(parent) = out_dir.parent() {
                tokio::fs::create_dir_all(parent).await?;
            }
            match tokio::fs::rename(&legacy_dir, &out_dir).await {
                Ok(()) => {
                    operation
                        .emit(
                            RunEvent::Warning {
                                message: format!(
                                    "Layout antigo migrado: {} -> {}",
                                    legacy_dir.display(),
                                    out_dir.display()
                                ),
                            },
                            Some(&board.board_url),
                            None,
                        )
                        .await;
                }
                Err(error) => {
                    // The rename can fail when the directories live on
                    // different filesystems. The old files stay where they
                    // are and are still reused.
                    operation
                        .emit(
                            RunEvent::Warning {
                                message: format!(
                                    "Nao foi possivel migrar o layout antigo ({}); os arquivos serao reutilizados onde estao",
                                    error
                                ),
                            },
                            Some(&board.board_url),
                            None,
                        )
                        .await;
                    reuse_dirs.push(legacy_dir.clone());
                }
            }
        } else if legacy_exists {
            reuse_dirs.push(legacy_dir.clone());
        }
    }
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
        cancellation.clone(),
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
    // A media URL that expired is resolved again during the download. The
    // fresh URL is written to the cache, so the next run does not start with
    // the expired one.
    let cache_changed = std::sync::atomic::AtomicBool::new(false);
    let download_controller = adaptive_controller(options);
    let pending = run_dynamic(
        board.pins.into_values().collect::<Vec<_>>(),
        options.workers,
        download_controller,
        cancellation.clone(),
        |result: &Result<crate::downloader::MediaDownload>| result.is_ok(),
        |pin| {
            let out_dir = &out_dir;
            let reuse_dirs = &reuse_dirs;
            let cache = &cache;
            let cache_changed = &cache_changed;
            async move {
                match downloader
                    .download_pin(&pin.image_url, out_dir, reuse_dirs, &pin.id, options)
                    .await
                {
                    Ok(media) => Ok(media),
                    Err(error) if error.is_expired_media() => {
                        // The signed URL of the media expired. The page of the
                        // pin still knows where the media lives, so the pin is
                        // resolved again. The identity of the pin does not
                        // change: the file keeps the name of the same pin.
                        let fresh = downloader
                            .resolve_pin(&pin.url, &pin.id, options.rate_limiting)
                            .await?;
                        let Some(fresh) = fresh else {
                            return Err(error);
                        };
                        if fresh.image_url == pin.image_url {
                            return Err(error);
                        }
                        if cache_enabled {
                            cache.lock().await.insert(&pin.url, &fresh.image_url);
                            cache_changed.store(true, std::sync::atomic::Ordering::Relaxed);
                        }
                        downloader
                            .download_pin(&fresh.image_url, out_dir, reuse_dirs, &pin.id, options)
                            .await
                    }
                    Err(error) => Err(error),
                }
            }
        },
    )
    .await;
    let mut legacy_reused = 0usize;
    for result in pending {
        operation.check_cancelled()?;
        match result {
            Ok(media) => {
                // A pin counts as downloaded, reused or failed, never as two of
                // them: the file has to be on disk before it counts as a
                // success. Otherwise the totals would not add up.
                let published = tokio::fs::metadata(&media.path)
                    .await
                    .is_ok_and(|meta| meta.is_file() && meta.len() > 0);
                if !published {
                    totals.failed += 1;
                } else if media.reused {
                    totals.reused += 1;
                    totals.verified += 1;
                    if media.from_legacy_layout {
                        legacy_reused += 1;
                    }
                } else {
                    totals.downloaded += 1;
                    totals.verified += 1;
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
    // The pins that were never resolved also failed, so the totals cover
    // every pin that was discovered.
    totals.failed += totals.discovered.saturating_sub(totals.resolved);
    if cache_enabled && cache_changed.load(std::sync::atomic::Ordering::Relaxed) {
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
    if legacy_reused > 0 {
        operation
            .emit(
                RunEvent::Warning {
                    message: format!(
                        "{legacy_reused} midia(s) vieram do layout antigo e nao foram baixadas de novo"
                    ),
                },
                Some(&board.board_url),
                None,
            )
            .await;
    }
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
    if board.origin.excluded_recommendations > 0 {
        operation
            .emit(
                RunEvent::Warning {
                    message: format!(
                        "{} pin(s) recomendado(s) nao pertencem ao quadro e foram descartados",
                        board.origin.excluded_recommendations
                    ),
                },
                Some(&board.board_url),
                None,
            )
            .await;
    }
    Ok(BoardReport {
        board_url: board.board_url,
        output_dir: out_dir,
        reason: board.reason,
        completeness: board.completeness,
        totals,
        origin: board.origin,
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
