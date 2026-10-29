//! URL helpers, normalization, filename sanitization and pin count parsing.

use regex::Regex;
use std::sync::LazyLock;

pub static USER_BOARDS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)^https?://(?:[a-z]{2}\.)?pinterest\.(?:com|[a-z]{2,3}(?:\.[a-z]{2})?)/([^/]+)/?$").unwrap()
});

static PIN_COUNT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"([\d.,]+)\s*(mil|k|m)?").unwrap()
});

pub fn normalize_url(raw: &str) -> String {
    let mut clean = raw.trim().to_string();
    if !clean.starts_with("http://") && !clean.starts_with("https://") {
        clean = format!("https://{}", clean);
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
        let clean_num = raw_num.replace('.', "").replace(',', "");
        clean_num.parse().ok()?
    };

    let multiplier = match multiplier_str {
        Some("mil") | Some("k") => 1_000.0,
        Some("m") => 1_000_000.0,
        _ => 1.0,
    };

    Some((val * multiplier).round() as u64)
}

pub fn safe_name(name: &str) -> String {
    sanitize_filename::sanitize(name)
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
}
