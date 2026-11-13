//! Parser for Pinterest pages and embedded __PWS_DATA__ structures.

use crate::models::{BoardMetadata, PinMetadata};
use regex::Regex;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::LazyLock;

static PWS_DATA_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?is)<script\b[^>]*\bid\s*=\s*["']__PWS_DATA__["'][^>]*>(.*?)</script\s*>"#)
        .unwrap()
});

pub fn extract_pws_metadata_from_html(html: &str) -> HashMap<String, PinMetadata> {
    let mut out = HashMap::new();
    if let Some(caps) = PWS_DATA_RE.captures(html) {
        if let Some(json_str) = caps.get(1) {
            if let Ok(val) = serde_json::from_str::<Value>(json_str.as_str()) {
                walk_pws_data(&val, &mut out);
            }
        }
    }
    out
}

pub fn extract_pin_metadata_from_value(value: &Value) -> HashMap<String, PinMetadata> {
    let mut pins = HashMap::new();
    walk_pws_data(value, &mut pins);
    pins
}

fn walk_pws_data(val: &Value, out: &mut HashMap<String, PinMetadata>) {
    match val {
        Value::Array(arr) => {
            for item in arr {
                walk_pws_data(item, out);
            }
        }
        Value::Object(map) => {
            if let Some(meta) = pin_from_pws_dict(map) {
                out.entry(meta.url.clone()).or_insert(meta);
            }
            for (key, v) in map {
                if is_recommendation_key(key) {
                    continue;
                }
                if v.is_array() || v.is_object() {
                    walk_pws_data(v, out);
                }
            }
        }
        _ => {}
    }
}

/// Whether a key of the Pinterest payload holds recommendations.
///
/// The payload of a board carries the pins of the board and, next to them,
/// the pins that Pinterest suggests. The suggestions live under keys whose
/// name says so, under many different names, and they are not part of the
/// board.
fn is_recommendation_key(key: &str) -> bool {
    let lower = key.to_ascii_lowercase();
    if lower.contains("recommend")
        || lower.contains("more_like_this")
        || lower.contains("more-like-this")
        || lower.contains("morelikethis")
    {
        return true;
    }
    // "related" and "suggested" as a word of the name, so that
    // `feed_related_pins` and `pins_suggested` are caught as well.
    lower
        .split(|character: char| !character.is_ascii_alphanumeric())
        .any(|word| {
            matches!(
                word,
                "related" | "suggest" | "suggests" | "suggested" | "suggestion" | "suggestions"
            )
        })
}

fn pin_from_pws_dict(d: &serde_json::Map<String, Value>) -> Option<PinMetadata> {
    let pid = d.get("entityId").or_else(|| d.get("id")).and_then(|v| {
        v.as_str()
            .map(str::to_owned)
            .or_else(|| v.as_u64().map(|n| n.to_string()))
    })?;
    if pid.is_empty() || !pid.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }

    let imgs_dict = d.get("images").and_then(|v| v.as_object());
    let flat_orig = d
        .get("images_orig")
        .or_else(|| d.get("images_736x"))
        .or_else(|| d.get("images_474x"))
        .and_then(|v| v.as_object());

    let mut iurl = None;
    if let Some(orig) = flat_orig {
        iurl = orig.get("url").and_then(|u| u.as_str());
    } else if let Some(dict) = imgs_dict {
        // The real Pinterest serves `originals` (and `750x`), while the
        // fixtures and the older payloads use `orig`. The bigger the
        // source, the better the candidate.
        let best = ["originals", "orig", "750x", "736x", "474x"]
            .iter()
            .find_map(|size| dict.get(*size).and_then(|v| v.as_object()));
        iurl = best.and_then(|b| b.get("url")).and_then(|u| u.as_str());
    }

    let image_url = iurl?.to_string();
    let title = d
        .get("title")
        .or_else(|| d.get("gridTitle"))
        .or_else(|| d.get("grid_title"))
        .and_then(|t| t.as_str())
        .unwrap_or("")
        .to_string();

    Some(PinMetadata {
        id: pid.to_string(),
        url: format!("https://www.pinterest.com/pin/{pid}/"),
        image_url,
        title,
    })
}

pub fn extract_boards_from_html(html: &str, username: &str) -> Vec<BoardMetadata> {
    PWS_DATA_RE
        .captures(html)
        .and_then(|caps| serde_json::from_str::<Value>(&caps[1]).ok())
        .map(|data| extract_boards_from_pws(&data, username))
        .unwrap_or_default()
}

pub fn extract_boards_from_pws(val: &Value, username: &str) -> Vec<BoardMetadata> {
    let mut boards = HashMap::new();
    let mut pending = vec![val];
    while let Some(value) = pending.pop() {
        match value {
            Value::Object(map) => {
                if let (Some(raw_url), Some(name)) = (
                    map.get("url").and_then(Value::as_str),
                    map.get("name").and_then(Value::as_str),
                ) {
                    if let Ok(url) = url::Url::parse("https://www.pinterest.com/")
                        .unwrap()
                        .join(raw_url)
                    {
                        let parts: Vec<_> = url
                            .path_segments()
                            .into_iter()
                            .flatten()
                            .filter(|part| !part.is_empty())
                            .collect();
                        if parts.len() == 2
                            && parts[0].eq_ignore_ascii_case(username)
                            && !parts[1].starts_with('_')
                            && !matches!(parts[1], "pins" | "boards" | "created" | "saved")
                        {
                            let count = map
                                .get("pin_count")
                                .map(|v| {
                                    v.as_str()
                                        .map(str::to_owned)
                                        .unwrap_or_else(|| v.to_string())
                                })
                                .unwrap_or_default();
                            // Keep relative links relative so local fixture servers work as well.
                            boards.entry(raw_url.to_string()).or_insert(BoardMetadata {
                                url: raw_url.to_string(),
                                title: name.to_string(),
                                thumbnail_url: String::new(),
                                pin_count_int: crate::utils::parse_pin_count(&count),
                                pin_count: count,
                            });
                        }
                    }
                }
                pending.extend(map.values());
            }
            Value::Array(values) => pending.extend(values),
            _ => {}
        }
    }
    let mut boards: Vec<_> = boards.into_values().collect();
    boards.sort_by(|a, b| a.url.cmp(&b.url));
    boards
}

/// Read metatags structurally (attribute order and HTML escaping are not significant).
/// JSON candidates must match the requested pin, not a recommendation on the page.
pub fn media_candidates_from_pin_html(html: &str, expected_id: &str) -> Vec<String> {
    let document = scraper::Html::parse_document(html);
    let selector = scraper::Selector::parse("meta[property][content]").unwrap();
    let mut candidates = Vec::new();
    let mut image = Vec::new();
    for tag in document.select(&selector) {
        let property = tag.value().attr("property").unwrap_or_default();
        let content = tag.value().attr("content").unwrap_or_default();
        if content.is_empty() {
            continue;
        }
        match property {
            "og:video:secure_url" | "og:video" => candidates.push(content.to_owned()),
            "og:image" => image.push(content.to_owned()),
            _ => {}
        }
    }
    if let Some(pin) = extract_pws_metadata_from_html(html)
        .into_values()
        .find(|pin| pin.id == expected_id)
    {
        candidates.push(pin.image_url);
    }
    candidates.extend(image);
    let mut seen = std::collections::HashSet::new();
    candidates.retain(|url| seen.insert(url.clone()));
    candidates
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pins_accept_script_attributes_and_resolution_fallbacks() {
        let html = r#"<script type='application/json' id='__PWS_DATA__'>
            {"data":[{"id":"42","images":{"474x":{"url":"https://i.pinimg.com/42.jpg"}}}]}
            </script>"#;
        let pins = extract_pws_metadata_from_html(html);
        assert_eq!(
            pins["https://www.pinterest.com/pin/42/"].image_url,
            "https://i.pinimg.com/42.jpg"
        );
        assert!(
            extract_pws_metadata_from_html("<script id='__PWS_DATA__'>invalid</script>").is_empty()
        );
    }

    #[test]
    fn boards_are_recursive_deduplicated_and_profile_specific() {
        let value = serde_json::json!({"props":{"resources":[
            {"url":"/alice/art/","name":"Art","pin_count":123},
            {"url":"/alice/art/","name":"Art","pin_count":123},
            {"url":"/bob/art/","name":"Other"},
            {"url":"/alice/_saved/","name":"Navigation"}
        ]}});
        let boards = extract_boards_from_pws(&value, "alice");
        assert_eq!(boards.len(), 1);
        assert_eq!(boards[0].pin_count_int, Some(123));
    }
    #[test]
    fn metatags_preserve_signed_queries_decode_entities_and_prefer_video() {
        let html = r#"<meta content='https://cdn.example/image.jpg?x=1&amp;y=2' property='og:image'>
            <meta property="og:video:secure_url" content="https://cdn.example/video.mp4?sig=keep">"#;
        let candidates = media_candidates_from_pin_html(html, "101");
        assert_eq!(
            candidates,
            vec![
                "https://cdn.example/video.mp4?sig=keep",
                "https://cdn.example/image.jpg?x=1&y=2"
            ]
        );
    }

    #[test]
    fn every_name_of_a_recommendation_is_rejected() {
        // The Pinterest changes the name of the suggestions over time. A
        // payload that hides a recommendation under another name would put a
        // pin of another board inside this one.
        for key in [
            "recommendations",
            "more_recommendations",
            "related_pins",
            "related_pins_resource",
            "feed_related_pins",
            "more_like_this",
            "moreLikeThis",
            "suggested_pins",
        ] {
            assert!(is_recommendation_key(key), "{key} was not rejected");
        }
        for key in ["pins", "resource_response", "data", "images", "grid_title"] {
            assert!(!is_recommendation_key(key), "{key} was rejected");
        }
    }

    #[test]
    fn a_recommendation_hidden_under_another_name_stays_out() {
        let data = serde_json::json!({"data":[{"id":"101","images":{"orig":{"url":"/101.jpg"}}}],
            "more_recommendations":[{"id":"999","images":{"orig":{"url":"/999.jpg"}}}]});
        let mut ids: Vec<_> = extract_pin_metadata_from_value(&data)
            .into_values()
            .map(|pin| pin.id)
            .collect();
        ids.sort();
        assert_eq!(ids, ["101"]);
    }

    #[test]
    fn a_media_with_the_name_originals_is_recognized() {
        // The real Pinterest serves `originals`, not `orig`. A pin whose
        // only media is `originals` used to be dropped entirely.
        let data = serde_json::json!({"data":[
            {"id":"777","images":{"originals":{"url":"https://i.pinimg.com/originals/777.jpg"}}}
        ]});
        let pins = extract_pin_metadata_from_value(&data);
        let found: Vec<_> = pins.values().collect();
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].id, "777");
        assert_eq!(found[0].image_url, "https://i.pinimg.com/originals/777.jpg");
    }

    #[test]
    fn the_largest_media_size_has_precedence() {
        let data = serde_json::json!({"data":[
            {"id":"778","images":{
                "originals":{"url":"/originals.jpg"},
                "750x":{"url":"/750.jpg"},
                "736x":{"url":"/736.jpg"},
                "474x":{"url":"/474.jpg"}
            }}
        ]});
        let pins = extract_pin_metadata_from_value(&data);
        let found: Vec<_> = pins.values().collect();
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].image_url, "/originals.jpg");
    }

    #[test]
    fn resource_graphql_metadata_rejects_recommendations_and_non_numeric_ids() {
        let data = serde_json::json!({"resource_response":{"data":[
            {"id":101,"images":{"orig":{"url":"/101.jpg"}}},
            {"entityId":"102","images_orig":{"url":"/102.jpg"}},
            {"id":"not-a-pin","images":{"orig":{"url":"/wrong.jpg"}}}
        ]}, "recommendations":[{"id":"999","images":{"orig":{"url":"/999.jpg"}}}]});
        let mut ids: Vec<_> = extract_pin_metadata_from_value(&data)
            .into_values()
            .map(|pin| pin.id)
            .collect();
        ids.sort();
        assert_eq!(ids, ["101", "102"]);
    }
}
