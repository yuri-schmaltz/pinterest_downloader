//! HTTP collection of embedded Pinterest metadata and atomic media downloads.

use crate::models::{BoardDownloadResult, DownloadOptions, PinterestError, Result};
use crate::parser::{extract_boards_from_html, extract_pws_metadata_from_html};
use crate::rate_limiter::RateLimiter;
use crate::utils::{detect_media_extension, safe_name};
use futures::{stream, StreamExt};
use reqwest::Client;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tokio::fs::{self, File};
use tokio::io::AsyncWriteExt;
use tracing::warn;

#[derive(Clone)]
pub struct Downloader {
    client: Client,
    limiter: Arc<RateLimiter>,
    cookies: Arc<reqwest::cookie::Jar>,
}

#[derive(Debug)]
pub struct MediaDownload {
    pub path: PathBuf,
    pub reused: bool,
}

impl Downloader {
    pub fn new() -> Result<Self> {
        let cookies = Arc::new(reqwest::cookie::Jar::default());
        let client = Client::builder()
            .cookie_provider(cookies.clone())
            .user_agent("Mozilla/5.0 PinterestDownloader/2")
            .connect_timeout(Duration::from_secs(15))
            .timeout(Duration::from_secs(120))
            .build()?;
        Ok(Self {
            client,
            limiter: Arc::new(RateLimiter::default()),
            cookies,
        })
    }

    /// How many times the rate limiter had to hold a request back.
    ///
    /// Zero across a run means the limiter was bypassed.
    pub fn limiter_waits(&self) -> u64 {
        self.limiter.waits()
    }

    /// Fetch one HTTP snapshot. This does not execute JavaScript or paginate feeds.
    pub(crate) async fn fetch_html(&self, url: &str, rate_limiting: bool) -> Result<String> {
        if rate_limiting {
            self.limiter.acquire().await;
        }
        Ok(self
            .client
            .get(url)
            .send()
            .await?
            .error_for_status()?
            .text()
            .await?)
    }

    /// A profile visits the boards embedded in its initial HTML; a board visits itself.
    pub async fn download_target(
        &self,
        target: &str,
        options: &DownloadOptions,
    ) -> Result<Vec<BoardDownloadResult>> {
        validate_options(options)?;
        let target = crate::utils::normalize_url(target);
        let url =
            url::Url::parse(&target).map_err(|_| PinterestError::InvalidUrl(target.clone()))?;
        if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
            return Err(PinterestError::InvalidUrl(target));
        }
        let html = self.fetch_html(&target, options.rate_limiting).await?;
        let parts: Vec<_> = url
            .path_segments()
            .into_iter()
            .flatten()
            .filter(|p| !p.is_empty())
            .collect();
        let mut pages = Vec::new();
        if parts.len() == 1 {
            let boards = extract_boards_from_html(&html, parts[0]);
            if boards.is_empty() {
                return Err(PinterestError::Extraction(
                    "Nenhum quadro no HTML inicial do perfil. Use a versão Python para páginas dinâmicas/login.".into(),
                ));
            }
            for board in boards {
                let board_url = url
                    .join(&board.url)
                    .map_err(|_| PinterestError::InvalidUrl(board.url.clone()))?;
                // Only follow boards belonging to the same profile and origin.
                if board_url.origin() == url.origin() {
                    let html = self
                        .fetch_html(board_url.as_str(), options.rate_limiting)
                        .await?;
                    pages.push((board_url.to_string(), html));
                }
            }
        } else if parts.len() == 2 && parts[0] != "pin" {
            pages.push((target, html));
        } else {
            return Err(PinterestError::InvalidUrl(target));
        }
        let mut results = Vec::new();
        for (board_url, html) in pages {
            let pins = extract_pws_metadata_from_html(&html)
                .into_values()
                .map(|pin| (pin.url, pin.image_url))
                .collect();
            results.push(
                self.download_board_images(&board_url, pins, options)
                    .await?,
            );
        }
        if results.is_empty() {
            return Err(PinterestError::Extraction(
                "Nenhum quadro válido encontrado".into(),
            ));
        }
        Ok(results)
    }

    pub async fn resolve_pin(
        &self,
        pin_url: &str,
        pin_id: &str,
        rate_limiting: bool,
    ) -> Result<Option<crate::PinMetadata>> {
        if rate_limiting {
            self.limiter.acquire().await;
        }
        let response = self.client.get(pin_url).send().await?.error_for_status()?;
        let final_url = response.url().clone();
        let parts: Vec<_> = final_url
            .path_segments()
            .into_iter()
            .flatten()
            .filter(|part| !part.is_empty())
            .collect();
        if parts.len() != 2 || parts[0] != "pin" || parts[1] != pin_id {
            return Err(PinterestError::Extraction(
                "Página do pin redirecionou para outro alvo/login".into(),
            ));
        }
        let html = response.text().await?;
        for candidate in crate::parser::media_candidates_from_pin_html(&html, pin_id) {
            if let Ok(url) = final_url.join(&candidate) {
                if matches!(url.scheme(), "http" | "https") {
                    return Ok(Some(crate::PinMetadata {
                        id: pin_id.into(),
                        url: pin_url.into(),
                        image_url: url.to_string(),
                        title: String::new(),
                    }));
                }
            }
        }
        Ok(None)
    }

    pub fn import_browser_cookies(&self, cookies: &[serde_json::Value]) {
        for cookie in cookies {
            let (Some(name), Some(value), Some(domain)) = (
                cookie["name"].as_str(),
                cookie["value"].as_str(),
                cookie["domain"].as_str(),
            ) else {
                continue;
            };
            let path = cookie["path"].as_str().unwrap_or("/");
            let secure = cookie["secure"].as_bool().unwrap_or(false);
            let scheme = if secure { "https" } else { "http" };
            if let Ok(url) =
                url::Url::parse(&format!("{scheme}://{}/", domain.trim_start_matches('.')))
            {
                let domain_attribute = if domain.starts_with('.') {
                    format!("; Domain={domain}")
                } else {
                    String::new()
                };
                let secure_attribute = if secure { "; Secure" } else { "" };
                self.cookies.add_cookie_str(
                    &format!("{name}={value}; Path={path}{domain_attribute}{secure_attribute}"),
                    &url,
                );
            }
        }
    }

    pub async fn download_pin(
        &self,
        media_url: &str,
        out_dir: &Path,
        pin_id: &str,
        options: &DownloadOptions,
    ) -> Result<MediaDownload> {
        self.download_media_with_options(
            media_url,
            out_dir,
            Some(pin_id),
            3,
            options.use_cache,
            options.rate_limiting,
        )
        .await
    }

    pub async fn download_media(
        &self,
        media_url: &str,
        out_dir: &Path,
        filename_hint: Option<&str>,
        max_retries: usize,
    ) -> Result<PathBuf> {
        self.download_media_with_options(media_url, out_dir, filename_hint, max_retries, true, true)
            .await
            .map(|result| result.path)
    }

    async fn download_media_with_options(
        &self,
        media_url: &str,
        out_dir: &Path,
        filename_hint: Option<&str>,
        max_retries: usize,
        use_cache: bool,
        rate_limiting: bool,
    ) -> Result<MediaDownload> {
        let base_name = safe_name(filename_hint.unwrap_or(media_url));
        if base_name.is_empty() {
            return Err(PinterestError::Extraction("Nome de arquivo vazio".into()));
        }
        if use_cache && out_dir.exists() {
            let mut entries = fs::read_dir(out_dir).await?;
            while let Some(entry) = entries.next_entry().await? {
                let path = entry.path();
                let ext = path.extension().and_then(|s| s.to_str()).unwrap_or("");
                let stem = path.file_stem().and_then(|s| s.to_str());
                let expected_stem = Path::new(&base_name).file_stem().and_then(|s| s.to_str());
                if matches!(ext, "jpg" | "jpeg" | "png" | "gif" | "webp" | "mp4")
                    && stem == expected_stem
                {
                    let meta = entry.metadata().await?;
                    if meta.is_file() && meta.len() > 0 {
                        return Ok(MediaDownload { path, reused: true });
                    }
                }
            }
        }
        fs::create_dir_all(out_dir).await?;
        for attempt in 0..=max_retries {
            if rate_limiting {
                self.limiter.acquire().await;
            }
            match self
                .download_attempt(media_url, out_dir, &base_name, rate_limiting)
                .await
            {
                Ok(path) => {
                    if rate_limiting {
                        self.limiter.record_success();
                    }
                    return Ok(MediaDownload {
                        path,
                        reused: false,
                    });
                }
                Err(error) if attempt == max_retries => return Err(error),
                Err(_) => {
                    let delay = Duration::from_millis(500 * (1u64 << attempt.min(6)));
                    tokio::time::sleep(delay).await;
                }
            }
        }
        unreachable!()
    }

    async fn download_attempt(
        &self,
        media_url: &str,
        out_dir: &Path,
        base_name: &str,
        rate_limiting: bool,
    ) -> Result<PathBuf> {
        let response = self.client.get(media_url).send().await?;
        if response.status().as_u16() == 429 && rate_limiting {
            let retry_after = response
                .headers()
                .get(reqwest::header::RETRY_AFTER)
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.parse::<u64>().ok())
                .map(Duration::from_secs);
            self.limiter.record_429(retry_after).await;
        }
        let response = response.error_for_status()?;
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        let ext = detect_media_extension(content_type);
        let dest = out_dir.join(Path::new(base_name).with_extension(ext.trim_start_matches('.')));
        // The temporary file is removed on error or cancellation. Only persist after EOF.
        let temporary = tempfile::Builder::new()
            .prefix(".pbd-")
            .suffix(".part")
            .tempfile_in(out_dir)?;
        let mut file = File::from_std(temporary.reopen()?);
        let mut chunks = response.bytes_stream();
        let mut bytes = 0;
        while let Some(chunk) = chunks.next().await {
            let chunk = chunk?;
            bytes += chunk.len();
            file.write_all(&chunk).await?;
        }
        if bytes == 0 {
            return Err(PinterestError::Extraction("Resposta de mídia vazia".into()));
        }
        file.flush().await?;
        file.sync_all().await?;
        drop(file);
        temporary
            .persist(&dest)
            .map_err(|error| PinterestError::Io(error.error))?;
        Ok(dest)
    }

    pub async fn download_board_images(
        &self,
        board_url: &str,
        pin_images: HashMap<String, String>,
        options: &DownloadOptions,
    ) -> Result<BoardDownloadResult> {
        validate_options(options)?;
        if pin_images.is_empty() {
            return Err(PinterestError::Extraction(
                "Nenhum pin encontrado no HTML inicial. A CLI Rust não executa scroll/login; use Python para coleta dinâmica.".into(),
            ));
        }
        let clean_url = crate::utils::normalize_url(board_url);
        let url = url::Url::parse(&clean_url)
            .map_err(|_| PinterestError::InvalidUrl(clean_url.clone()))?;
        let parts: Vec<_> = url
            .path_segments()
            .into_iter()
            .flatten()
            .filter(|s| !s.is_empty())
            .collect();
        let target_dir = options.out_root.join(safe_name(&parts.join("_")));
        let mut pins: Vec<_> = pin_images.into_iter().collect();
        pins.sort_by(|a, b| a.0.cmp(&b.0));
        if let Some(limit) = options.max_pins {
            pins.truncate(limit);
        }
        let total = pins.len();
        let outcomes: Vec<_> = stream::iter(pins.into_iter().map(|(pin_url, img_url)| {
            let out_dir = target_dir.clone();
            async move {
                let hint = pin_url
                    .trim_end_matches('/')
                    .rsplit('/')
                    .next()
                    .unwrap_or("pin");
                self.download_media_with_options(
                    &img_url,
                    &out_dir,
                    Some(hint),
                    3,
                    options.use_cache,
                    options.rate_limiting,
                )
                .await
            }
        }))
        .buffer_unordered(options.workers)
        .collect()
        .await;
        let mut downloaded = 0;
        for result in outcomes {
            match result {
                Ok(_) => downloaded += 1,
                Err(error) => warn!("Falha no download: {error}"),
            }
        }
        Ok(BoardDownloadResult {
            board_url: clean_url,
            downloaded,
            total,
            output_dir: target_dir,
        })
    }
}

fn validate_options(options: &DownloadOptions) -> Result<()> {
    if options.workers == 0 || options.max_pins == Some(0) {
        return Err(PinterestError::Extraction(
            "workers e max-pins devem ser maiores que zero".into(),
        ));
    }
    Ok(())
}
