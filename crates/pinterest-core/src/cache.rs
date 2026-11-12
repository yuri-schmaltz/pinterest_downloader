//! Persistent cache of pin metadata.
//!
//! Mirrors the Python `.pinterest_cache.json`: a JSON object mapping the pin
//! URL to the media URL that was resolved for it. The file format is the same
//! on both sides, so a cache directory can be shared between the Python and
//! the Rust CLI.
//!
//! The cache is an optimisation, never a source of truth: a missing, empty or
//! corrupt file yields an empty cache instead of failing the run, and a failed
//! write is reported as a warning.

use crate::Result;
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use tokio::fs;

const CACHE_FILE_NAME: &str = ".pinterest_cache.json";
const APP_DIR_NAME: &str = "pinterest-downloader";

/// Resolve the cache directory.
///
/// An explicit override always wins. Otherwise the platform default applies:
/// `XDG_CACHE_HOME` on Linux/macOS and `LOCALAPPDATA` on Windows.
pub fn resolve_cache_dir(override_dir: Option<&Path>) -> PathBuf {
    if let Some(dir) = override_dir {
        return dir.to_path_buf();
    }
    if cfg!(windows) {
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            return PathBuf::from(local).join(APP_DIR_NAME);
        }
    }
    if let Some(xdg) = std::env::var_os("XDG_CACHE_HOME") {
        return PathBuf::from(xdg).join(APP_DIR_NAME);
    }
    if let Some(home) = std::env::var_os("HOME") {
        return PathBuf::from(home).join(".cache").join(APP_DIR_NAME);
    }
    if let Some(profile) = std::env::var_os("USERPROFILE") {
        return PathBuf::from(profile)
            .join("AppData")
            .join("Local")
            .join(APP_DIR_NAME);
    }
    PathBuf::from(".").join(APP_DIR_NAME)
}

/// In-memory view of the pin metadata cache.
#[derive(Debug)]
pub struct PinCache {
    entries: BTreeMap<String, String>,
    path: PathBuf,
    dirty: bool,
}

impl PinCache {
    /// Load the cache stored in `dir`.
    ///
    /// A missing file yields an empty cache. A file that is not a JSON object
    /// of strings is discarded rather than propagated, so a cache written by
    /// another version cannot break a run.
    pub fn load(dir: &Path) -> Self {
        let path = dir.join(CACHE_FILE_NAME);
        let entries = std::fs::read_to_string(&path)
            .ok()
            .map(|raw| parse_entries(&raw))
            .unwrap_or_default();
        Self {
            entries,
            path,
            dirty: false,
        }
    }

    /// An empty cache that is never persisted.
    ///
    /// Used when metadata caching is disabled: nothing is read from disk and
    /// nothing is written back.
    pub fn disabled() -> Self {
        Self {
            entries: BTreeMap::new(),
            path: PathBuf::new(),
            dirty: false,
        }
    }

    /// The media URL previously resolved for `pin_url`, if any.
    pub fn get(&self, pin_url: &str) -> Option<&str> {
        self.entries.get(pin_url).map(String::as_str)
    }

    /// Remember the media URL resolved for `pin_url`.
    pub fn insert(&mut self, pin_url: &str, media_url: &str) {
        self.entries
            .insert(pin_url.to_string(), media_url.to_string());
        self.dirty = true;
    }

    /// Number of cached pins.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether the cache has no entries.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Where the cache is persisted.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Persist the cache.
    ///
    /// The file is written to a temporary name first and then renamed, so an
    /// interrupted run never leaves a truncated cache behind.
    pub async fn save(&mut self) -> Result<()> {
        if !self.dirty || self.path.as_os_str().is_empty() {
            return Ok(());
        }
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).await?;
        }
        let payload = serde_json::to_string_pretty(&self.entries)?;
        let temporary = self.path.with_extension("json.part");
        fs::write(&temporary, payload).await?;
        fs::rename(&temporary, &self.path).await?;
        self.dirty = false;
        Ok(())
    }
}

/// Reads a JSON object of strings without assuming the file is well formed.
pub fn parse_entries(raw: &str) -> BTreeMap<String, String> {
    let Ok(Value::Object(map)) = serde_json::from_str::<Value>(raw) else {
        return BTreeMap::new();
    };
    map.into_iter()
        .filter_map(|(key, value)| value.as_str().map(|value| (key, value.to_string())))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_directory_wins_over_the_platform_default() {
        let chosen = resolve_cache_dir(Some(Path::new("/tmp/custom-cache")));
        assert_eq!(chosen, PathBuf::from("/tmp/custom-cache"));
    }

    #[test]
    fn corrupt_or_unexpected_content_yields_an_empty_cache() {
        assert!(parse_entries("not json").is_empty());
        assert!(parse_entries("[1, 2, 3]").is_empty());
        let entries = parse_entries(r#"{"a": "b", "c": 3}"#);
        assert_eq!(entries.len(), 1);
        assert_eq!(entries.get("a").map(String::as_str), Some("b"));
    }
}
