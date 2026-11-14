//! Core models, errors and types for Pinterest Downloader.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum PinterestError {
    #[error("Operation cancelled")]
    Cancelled,

    #[error("Browser error: {0}")]
    Browser(String),

    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("Authentication required: {0}. Use a visible browser and manual login.")]
    AuthenticationRequired(String),

    #[error("Private profile detected: '{0}'. Manual login is required.")]
    PrivateProfile(String),

    #[error("Invalid URL: {0}")]
    InvalidUrl(String),

    #[error("Rate limited (HTTP 429). Retry after {0} seconds.")]
    RateLimited(u64),

    #[error("Extraction failure: {0}")]
    Extraction(String),
}

impl PinterestError {
    /// Whether the failure means the URL of the media is no longer valid.
    ///
    /// A signed URL that expired answers with 403, 404 or 410. Trying it
    /// again only wastes time: the page of the pin has to say where the
    /// media lives now.
    pub fn is_expired_media(&self) -> bool {
        match self {
            Self::Network(error) => matches!(
                error.status().map(|status| status.as_u16()),
                Some(403) | Some(404) | Some(410)
            ),
            _ => false,
        }
    }
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
    /// The board the pin was saved to, when the payload says so.
    ///
    /// A board page also asks for the feeds of other boards. The pin that
    /// comes from another board is not part of the target, and the payload
    /// is what says so.
    #[serde(default)]
    pub board_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadOptions {
    pub out_root: PathBuf,
    pub workers: usize,
    pub use_cache: bool,
    pub rate_limiting: bool,
    pub max_pins: Option<usize>,
    /// How many boards are processed at the same time. Each one gets its own
    /// browser and its own HTTP client, so the total concurrency is this
    /// times `workers`.
    pub boards_workers: usize,
    /// Directory of the pin metadata cache. `None` uses the platform default.
    pub cache_dir: Option<PathBuf>,
    /// Whether the pin metadata cache is read and written.
    pub metadata_cache: bool,
    /// Whether the number of tasks in flight follows the machine load.
    pub adaptive: bool,
    /// How long the pin metadata cache stays usable. Zero never expires it.
    pub cache_ttl: std::time::Duration,
}

impl Default for DownloadOptions {
    fn default() -> Self {
        Self {
            out_root: PathBuf::from("downloads"),
            workers: 8,
            use_cache: true,
            rate_limiting: true,
            max_pins: None,
            boards_workers: 1,
            cache_dir: None,
            metadata_cache: true,
            adaptive: false,
            cache_ttl: crate::cache::DEFAULT_TTL,
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
