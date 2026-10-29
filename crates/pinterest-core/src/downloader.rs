//! Downloader implementation in Rust using Tokio and Reqwest.

use crate::models::{BoardDownloadResult, DownloadOptions, PinterestError, Result};
use crate::rate_limiter::RateLimiter;
use crate::utils::{detect_media_extension, safe_name};
use futures::StreamExt;
use reqwest::Client;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::fs::{self, File};
use tokio::io::AsyncWriteExt;
use tokio::sync::Semaphore;
use tracing::{info, warn};

pub struct Downloader {
    client: Client,
    limiter: Arc<RateLimiter>,
}

impl Downloader {
    pub fn new() -> Result<Self> {
        let client = Client::builder()
            .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            .build()?;

        Ok(Self {
            client,
            limiter: Arc::new(RateLimiter::default()),
        })
    }

    pub async fn download_media(
        &self,
        media_url: &str,
        out_dir: &Path,
        filename_hint: Option<&str>,
        max_retries: usize,
    ) -> Result<PathBuf> {
        let base_name = safe_name(filename_hint.unwrap_or(media_url));

        // Pre-check: se arquivo já existe com stem e > 0 bytes, skip
        if out_dir.exists() {
            let mut entries = fs::read_dir(out_dir).await?;
            while let Some(entry) = entries.next_entry().await? {
                let name = entry.file_name();
                let name_str = name.to_string_lossy();
                if name_str.starts_with(&base_name) {
                    if let Ok(meta) = entry.metadata().await {
                        if meta.len() > 0 {
                            return Ok(entry.path());
                        }
                    }
                }
            }
        }

        fs::create_dir_all(out_dir).await?;

        let mut attempt = 0;
        loop {
            self.limiter.acquire().await;

            match self.client.get(media_url).send().await {
                Ok(resp) => {
                    let status = resp.status();
                    if status.as_u16() == 429 {
                        self.limiter.record_429(None).await;
                        if attempt < max_retries {
                            attempt += 1;
                            tokio::time::sleep(std::time::Duration::from_millis(500 * (1 << attempt))).await;
                            continue;
                        }
                        return Err(PinterestError::RateLimited(5));
                    }

                    if let Err(e) = resp.error_for_status_ref() {
                        if attempt < max_retries {
                            attempt += 1;
                            tokio::time::sleep(std::time::Duration::from_millis(500 * (1 << attempt))).await;
                            continue;
                        }
                        return Err(PinterestError::Network(e));
                    }

                    let content_type = resp
                        .headers()
                        .get(reqwest::header::CONTENT_TYPE)
                        .and_then(|v| v.to_str().ok())
                        .unwrap_or("");

                    let ext = detect_media_extension(content_type);
                    let final_name = if base_name.ends_with(ext) {
                        base_name.clone()
                    } else {
                        format!("{}{}", base_name, ext)
                    };

                    let dest = out_dir.join(final_name);
                    let mut file = File::create(&dest).await?;
                    let mut stream = resp.bytes_stream();

                    while let Some(chunk_res) = stream.next().await {
                        let chunk = chunk_res?;
                        file.write_all(&chunk).await?;
                    }

                    file.flush().await?;
                    self.limiter.record_success();
                    return Ok(dest);
                }
                Err(e) => {
                    if attempt < max_retries {
                        attempt += 1;
                        tokio::time::sleep(std::time::Duration::from_millis(500 * (1 << attempt))).await;
                    } else {
                        return Err(PinterestError::Network(e));
                    }
                }
            }
        }
    }

    pub async fn download_board_images(
        &self,
        board_url: &str,
        pin_images: HashMap<String, String>,
        options: &DownloadOptions,
    ) -> Result<BoardDownloadResult> {
        let clean_url = crate::utils::normalize_url(board_url);
        let board_slug = safe_name(clean_url.trim_end_matches('/').split('/').last().unwrap_or("board"));
        let target_dir = options.out_root.join(board_slug);

        info!("Baixando {} imagens para {:?}", pin_images.len(), target_dir);

        let sem = Arc::new(Semaphore::new(options.workers));
        let mut tasks = Vec::new();

        for (pin_url, img_url) in pin_images {
            let sem_clone = sem.clone();
            let out_dir_clone = target_dir.clone();
            let downloader_clone = self.clone();

            tasks.push(tokio::spawn(async move {
                let _permit = sem_clone.acquire().await.unwrap();
                let hint = safe_name(&pin_url);
                downloader_clone.download_media(&img_url, &out_dir_clone, Some(&hint), 3).await
            }));
        }

        let mut downloaded = 0;
        let total = tasks.len();

        for task in tasks {
            if let Ok(res) = task.await {
                if res.is_ok() {
                    downloaded += 1;
                }
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

impl Clone for Downloader {
    fn clone(&self) -> Self {
        Self {
            client: self.client.clone(),
            limiter: self.limiter.clone(),
        }
    }
}
