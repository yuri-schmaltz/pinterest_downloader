//! Core models, errors and types for Pinterest Downloader.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum PinterestError {
    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("Private profile detected: '{0}'. Manual login is required.")]
    PrivateProfile(String),

    #[error("Invalid URL: {0}")]
    InvalidUrl(String),

    #[error("Rate limited (HTTP 429). Retry after {0} seconds.")]
    RateLimited(u64),

    #[error("Extraction failure: {0}")]
    Extraction(String),
}

pub type Result<T> = std::result::Result<T, PinterestError>;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BoardMetadata {
    pub url: String,
    pub title: String,
    pub thumbnail_url: String,
    pub pin_count: String,
    pub pin_count_int: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PinMetadata {
    pub id: String,
    pub url: String,
    pub image_url: String,
    pub title: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadOptions {
    pub out_root: PathBuf,
    pub workers: usize,
    pub use_cache: bool,
    pub rate_limiting: bool,
    pub max_pins: Option<usize>,
}

impl Default for DownloadOptions {
    fn default() -> Self {
        Self {
            out_root: PathBuf::from("downloads"),
            workers: 8,
            use_cache: true,
            rate_limiting: true,
            max_pins: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BoardDownloadResult {
    pub board_url: String,
    pub downloaded: usize,
    pub total: usize,
    pub output_dir: PathBuf,
}
