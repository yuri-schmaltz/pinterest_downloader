//! A bounded cache of thumbnails.
//!
//! A profile can have hundreds of boards and each cover is an image. Keeping
//! them all in memory is what makes a list slow, so the cache has a limit
//! and throws away the oldest when it is full.

use std::collections::{HashMap, VecDeque};

/// A cache of thumbnails with a fixed number of entries.
#[derive(Debug, Clone)]
pub struct ThumbnailCache<T> {
    capacity: usize,
    entries: HashMap<String, T>,
    order: VecDeque<String>,
}

impl<T> ThumbnailCache<T> {
    /// A cache that holds at most `capacity` thumbnails.
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity: capacity.max(1),
            entries: HashMap::new(),
            order: VecDeque::new(),
        }
    }

    pub fn capacity(&self) -> usize {
        self.capacity
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Whether the thumbnail of a board is already in memory.
    pub fn contains(&self, key: &str) -> bool {
        self.entries.contains_key(key)
    }

    /// The thumbnail of a board, if it is still in memory.
    pub fn get(&self, key: &str) -> Option<&T> {
        self.entries.get(key)
    }

    /// Put a thumbnail in the cache.
    ///
    /// When the cache is full the oldest entry goes out, so a long list
    /// does not grow the memory without end.
    pub fn insert(&mut self, key: impl Into<String>, value: T) {
        let key = key.into();
        if self.entries.contains_key(&key) {
            // The thumbnail was just used, so it is the newest one and not
            // the one that goes out.
            self.order.retain(|existing| existing != &key);
        }
        self.entries.insert(key.clone(), value);
        self.order.push_back(key);
        while self.entries.len() > self.capacity {
            let Some(oldest) = self.order.pop_front() else {
                break;
            };
            self.entries.remove(&oldest);
        }
    }

    /// Forget everything.
    pub fn clear(&mut self) {
        self.entries.clear();
        self.order.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn o_cache_nao_cresce_para_cima_da_limite() {
        let mut cache = ThumbnailCache::new(3);
        for index in 0..10 {
            cache.insert(format!("board-{index}"), index);
        }
        assert_eq!(cache.len(), 3);
        assert_eq!(cache.capacity(), 3);
    }

    #[test]
    fn o_mais_antigo_sai_primeiro() {
        let mut cache = ThumbnailCache::new(2);
        cache.insert("a", 1);
        cache.insert("b", 2);
        cache.insert("c", 3);
        assert!(!cache.contains("a"));
        assert!(cache.contains("b"));
        assert!(cache.contains("c"));
    }

    #[test]
    fn a_thumbnail_que_volta_nao_conta_de_novo() {
        let mut cache = ThumbnailCache::new(2);
        cache.insert("a", 1);
        cache.insert("b", 2);
        cache.insert("a", 9);
        assert_eq!(cache.len(), 2);
        assert_eq!(cache.get("a"), Some(&9));
        cache.insert("c", 3);
        assert!(cache.contains("a"), "o quadro que voltou nao pode sair");
        assert!(!cache.contains("b"));
    }

    #[test]
    fn uma_capacidade_zero_ainda_guarda_um() {
        let mut cache = ThumbnailCache::new(0);
        cache.insert("a", 1);
        assert_eq!(cache.len(), 1);
    }
}
