//! Parser for Pinterest pages and embedded __PWS_DATA__ structures.

use crate::models::{BoardMetadata, PinMetadata};
use regex::Regex;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::LazyLock;

static PWS_DATA_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?s)<script id="__PWS_DATA__"[^>]*>(.*?)</script>"#).unwrap()
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
            for v in map.values() {
                if v.is_array() || v.is_object() {
                    walk_pws_data(v, out);
                }
            }
        }
        _ => {}
    }
}

fn pin_from_pws_dict(d: &serde_json::Map<String, Value>) -> Option<PinMetadata> {
    let pid = d.get("entityId")
        .or_else(|| d.get("id"))
        .and_then(|v| v.as_str())?;

    let imgs_dict = d.get("images").and_then(|v| v.as_object());
    let flat_orig = d.get("images_orig")
        .or_else(|| d.get("images_736x"))
        .or_else(|| d.get("images_474x"))
        .and_then(|v| v.as_object());

    let mut iurl = None;
    if let Some(orig) = flat_orig {
        iurl = orig.get("url").and_then(|u| u.as_str());
    } else if let Some(dict) = imgs_dict {
        let best = dict.get("orig")
            .or_else(|| dict.get("736x"))
            .and_then(|v| v.as_object());
        iurl = best.and_then(|b| b.get("url")).and_then(|u| u.as_str());
    }

    let image_url = iurl?.to_string();
    let title = d.get("title")
        .or_else(|| d.get("gridTitle"))
        .or_else(|| d.get("grid_title"))
        .and_then(|t| t.as_str())
        .unwrap_or("")
        .to_string();

    Some(PinMetadata {
        id: pid.to_string(),
        url: format!("https://www.pinterest.com/pin/{}/", pid),
        image_url,
        title,
    })
}

pub fn extract_boards_from_pws(val: &Value, username: &str) -> Vec<BoardMetadata> {
    let mut boards = Vec::new();
    // Navega em busca de boards de perfil
    if let Value::Object(map) = val {
        if let Some(data) = map.get("boards").and_then(|b| b.as_array()) {
            for b in data {
                if let Some(b_map) = b.as_object() {
                    let name = b_map.get("name").and_then(|n| n.as_str()).unwrap_or("");
                    let url = b_map.get("url").and_then(|u| u.as_str()).unwrap_or("");
                    let count_str = b_map.get("pin_count").and_then(|c| c.as_str()).unwrap_or("");
                    if !url.is_empty() {
                        let full_url = if url.starts_with("http") {
                            url.to_string()
                        } else {
                            format!("https://www.pinterest.com{}", url)
                        };
                        boards.push(BoardMetadata {
                            url: full_url,
                            title: name.to_string(),
                            thumbnail_url: "".to_string(),
                            pin_count: count_str.to_string(),
                            pin_count_int: crate::utils::parse_pin_count(count_str),
                        });
                    }
                }
            }
        }
    }
    boards
}
