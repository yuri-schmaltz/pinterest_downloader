//! URL helpers, normalization, filename sanitization and pin count parsing.

use regex::Regex;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use unicode_normalization::UnicodeNormalization;

pub static USER_BOARDS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?i)^https?://(?:[a-z]{2}\.)?pinterest\.(?:com|[a-z]{2,3}(?:\.[a-z]{2})?)/([^/]+)/?$",
    )
    .unwrap()
});

static PIN_COUNT_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"([\d.,]+)\s*(mil|k|m)?").unwrap());

pub fn normalize_url(raw: &str) -> String {
    let mut clean = raw.trim().to_string();
    if !clean.starts_with("http://") && !clean.starts_with("https://") {
        clean = if clean.split('/').next().unwrap_or("").contains('.') {
            format!("https://{clean}")
        } else {
            format!(
                "https://www.pinterest.com/{}",
                clean.trim_start_matches('/')
            )
        };
    }
    if let Some(pos) = clean.find('?') {
        clean.truncate(pos);
    }
    if !clean.ends_with('/') {
        clean.push('/');
    }
    clean
}

pub fn parse_pin_count(raw: &str) -> Option<u64> {
    let text = raw.trim().to_lowercase();
    let caps = PIN_COUNT_RE.captures(&text)?;

    let raw_num = caps.get(1)?.as_str();
    let multiplier_str = caps.get(2).map(|m| m.as_str());

    let val: f64 = if multiplier_str.is_some() {
        // Quando há multiplicador (ex: "1,2 mil" ou "2.5k"), ponto ou vírgula representam decimal
        let decimal_str = raw_num.replace(',', ".");
        decimal_str.parse().ok()?
    } else {
        // Sem multiplicador (ex: "1.200" ou "1,200 pins"), remove separador de milhar
        let clean_num = raw_num.replace(['.', ','], "");
        clean_num.parse().ok()?
    };

    let multiplier = match multiplier_str {
        Some("mil" | "k") => 1_000.0,
        Some("m") => 1_000_000.0,
        _ => 1.0,
    };

    Some((val * multiplier).round() as u64)
}

pub fn safe_name(name: &str) -> String {
    sanitize_filename::sanitize(name)
}

/// Percent-decodes a URL component the way the Python tool does.
///
/// The Python implementation runs `urllib.parse.unquote` on the path
/// component before turning it into a directory name, so the Rust side has to
/// decode it too or the two tools would write to different directories.
pub fn percent_decode(value: &str) -> String {
    percent_encoding::percent_decode_str(value)
        .decode_utf8_lossy()
        .into_owned()
}

/// Builds a directory component the same way the Python `slugify` does.
///
/// Unicode is preserved, whitespace is collapsed and path separators become
/// the fullwidth slash, so a board named "Casa / Jardim" lands in the same
/// directory no matter which tool downloaded it.
pub fn slugify(name: &str) -> String {
    let decoded = percent_decode(name);
    let normalized: String = decoded.nfc().collect();
    let mut out = String::with_capacity(normalized.len());
    let mut pending_space = false;
    for character in normalized.chars() {
        let character = match character {
            '\u{00a0}' => ' ',
            '\n' | '\r' | '\t' => ' ',
            '\u{0000}' => continue,
            other => other,
        };
        if character.is_whitespace() {
            // Collapse any run of whitespace into a single space, and drop the
            // leading one, the same way the Python regular expression does.
            pending_space = !out.is_empty();
            continue;
        }
        if pending_space {
            out.push(' ');
            pending_space = false;
        }
        out.push(character);
    }
    let out = out.replace('/', "\u{ff0f}");
    if out.is_empty() {
        "sem_nome".to_string()
    } else {
        out
    }
}

/// The user and the board of a board URL, already decoded.
pub fn split_user_board(url: &url::Url) -> (String, String) {
    let parts: Vec<_> = url
        .path_segments()
        .into_iter()
        .flatten()
        .filter(|part| !part.is_empty())
        .collect();
    let user = parts
        .first()
        .map(|part| percent_decode(part))
        .unwrap_or_default();
    let board = parts
        .get(1)
        .map(|part| percent_decode(part))
        .unwrap_or_default();
    (user, board)
}

/// Where the board files live, in the layout shared with the Python tool:
/// `<out_root>/<user>/<board>`.
pub fn board_output_dir(out_root: &Path, board_url: &url::Url) -> PathBuf {
    let (user, board) = split_user_board(board_url);
    out_root.join(slugify(&user)).join(slugify(&board))
}

/// Where earlier Rust builds wrote the same board: a single directory named
/// `<user>_<board>`. The files are still valid and must not be downloaded
/// again, so the engine looks here before writing anything new.
pub fn legacy_board_output_dir(out_root: &Path, board_url: &url::Url) -> PathBuf {
    let (user, board) = split_user_board(board_url);
    out_root.join(safe_name(&format!("{user}_{board}")))
}

pub fn detect_media_extension(content_type: &str) -> &'static str {
    if content_type.contains("video/mp4") {
        ".mp4"
    } else if content_type.contains("image/png") {
        ".png"
    } else if content_type.contains("image/gif") {
        ".gif"
    } else if content_type.contains("image/webp") {
        ".webp"
    } else {
        ".jpg"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_url() {
        assert_eq!(
            normalize_url("pinterest.com/user/board"),
            "https://pinterest.com/user/board/"
        );
        assert_eq!(
            normalize_url("https://br.pinterest.com/user/board?foo=bar"),
            "https://br.pinterest.com/user/board/"
        );
    }

    #[test]
    fn test_parse_pin_count() {
        assert_eq!(parse_pin_count("340 pins"), Some(340));
        assert_eq!(parse_pin_count("1,2 mil pins"), Some(1200));
        assert_eq!(parse_pin_count("2.5k"), Some(2500));
        assert_eq!(parse_pin_count("15 pins"), Some(15));
        assert_eq!(parse_pin_count(""), None);
    }

    #[test]
    fn test_detect_media_extension() {
        assert_eq!(detect_media_extension("image/png"), ".png");
        assert_eq!(detect_media_extension("video/mp4"), ".mp4");
        assert_eq!(detect_media_extension("image/jpeg"), ".jpg");
    }

    #[test]
    fn slugify_matches_the_python_behaviour() {
        // Unicode is preserved, whitespace collapses and slashes become the
        // fullwidth slash instead of creating a directory.
        assert_eq!(slugify("  Casa \n / Jardim "), "Casa ／ Jardim");
        assert_eq!(slugify("Decoração"), "Decoração");
        assert_eq!(slugify(""), "sem_nome");
        assert_eq!(slugify("///"), "／／／");
        assert_eq!(slugify("a\u{00a0}b"), "a b");
        // The Python tool percent-decodes before it slugifies.
        assert_eq!(slugify("casa%20e"), "casa e");
    }

    #[test]
    fn the_board_layout_is_shared_with_the_python_tool() {
        let url = url::Url::parse("https://www.pinterest.com/alice/decoracao/").unwrap();
        let root = Path::new("/tmp/downloads");
        assert_eq!(
            board_output_dir(root, &url),
            Path::new("/tmp/downloads/alice/decoracao")
        );
        // The legacy Rust layout was a single directory with an underscore.
        assert_eq!(
            legacy_board_output_dir(root, &url),
            Path::new("/tmp/downloads/alice_decoracao")
        );
    }

    #[test]
    fn percent_encoded_names_land_in_the_same_directory_as_python() {
        let url = url::Url::parse("https://www.pinterest.com/alice/casa%20e%20jardim/").unwrap();
        assert_eq!(
            board_output_dir(Path::new("/tmp"), &url),
            Path::new("/tmp/alice/casa e jardim")
        );
    }
}
