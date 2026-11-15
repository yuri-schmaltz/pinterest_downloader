//! The list of boards the user chooses from.
//!
//! The model lives apart from the drawing so that the rules can be tested
//! without a screen: which boards are visible, which ones are chosen, and
//! what happens to the choice when the filter changes.

use pinterest_core::BoardMetadata;
use std::collections::BTreeSet;

/// A board of the profile, as the list shows it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoardEntry {
    pub url: String,
    pub title: String,
    pub thumbnail_url: String,
    pub pin_count: Option<u64>,
}

impl From<&BoardMetadata> for BoardEntry {
    fn from(board: &BoardMetadata) -> Self {
        Self {
            url: board.url.clone(),
            title: if board.title.is_empty() {
                board.url.clone()
            } else {
                board.title.clone()
            },
            thumbnail_url: board.thumbnail_url.clone(),
            pin_count: board.pin_count_int,
        }
    }
}

/// The list of boards, the filter and the choice.
#[derive(Debug, Clone, Default)]
pub struct BoardSelection {
    boards: Vec<BoardEntry>,
    filter: String,
    selected: BTreeSet<String>,
}

impl BoardSelection {
    pub fn new() -> Self {
        Self::default()
    }

    /// Replace the list of boards.
    ///
    /// The choice of the user is kept for the boards that are still there:
    /// a new discovery does not throw away what was already chosen.
    pub fn set_boards(&mut self, boards: Vec<BoardEntry>) {
        let known: BTreeSet<String> = boards.iter().map(|board| board.url.clone()).collect();
        self.selected.retain(|url| known.contains(url));
        self.boards = boards;
    }

    pub fn boards(&self) -> &[BoardEntry] {
        &self.boards
    }

    pub fn filter(&self) -> &str {
        &self.filter
    }

    /// Change the filter. The choice of the user is not touched: a filter
    /// hides, it does not deselect.
    pub fn set_filter(&mut self, filter: impl Into<String>) {
        self.filter = filter.into();
    }

    /// The boards the filter leaves visible, in the order of the list.
    pub fn visible(&self) -> Vec<&BoardEntry> {
        let needle = self.filter.trim().to_lowercase();
        if needle.is_empty() {
            return self.boards.iter().collect();
        }
        self.boards
            .iter()
            .filter(|board| {
                board.title.to_lowercase().contains(&needle)
                    || board.url.to_lowercase().contains(&needle)
            })
            .collect()
    }

    pub fn visible_count(&self) -> usize {
        self.visible().len()
    }

    pub fn is_selected(&self, url: &str) -> bool {
        self.selected.contains(url)
    }

    pub fn selected_count(&self) -> usize {
        self.selected.len()
    }

    /// Choose or unchoose one board.
    pub fn toggle(&mut self, url: &str) {
        if !self.selected.remove(url) {
            self.selected.insert(url.to_owned());
        }
    }

    /// Choose every board the filter leaves visible.
    ///
    /// A filter that hides boards does not choose the hidden ones, and the
    /// boards chosen before the filter keep their choice.
    pub fn select_all_visible(&mut self) {
        let urls: Vec<String> = self.visible().into_iter().map(|b| b.url.clone()).collect();
        for url in urls {
            self.selected.insert(url);
        }
    }

    /// Unchoose everything.
    pub fn clear_selection(&mut self) {
        self.selected.clear();
    }

    /// The chosen boards, in the order of the list.
    pub fn selected_boards(&self) -> Vec<&BoardEntry> {
        self.boards
            .iter()
            .filter(|board| self.selected.contains(&board.url))
            .collect()
    }

    /// The addresses of the chosen boards, ready for the engine.
    pub fn selected_urls(&self) -> Vec<String> {
        self.selected_boards()
            .into_iter()
            .map(|board| board.url.clone())
            .collect()
    }

    /// Whether every visible board is chosen.
    pub fn all_visible_selected(&self) -> bool {
        let visible = self.visible();
        !visible.is_empty()
            && visible
                .iter()
                .all(|board| self.selected.contains(&board.url))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn board(url: &str, title: &str) -> BoardEntry {
        BoardEntry {
            url: url.to_owned(),
            title: title.to_owned(),
            thumbnail_url: String::new(),
            pin_count: None,
        }
    }

    fn sample() -> BoardSelection {
        let mut selection = BoardSelection::new();
        selection.set_boards(vec![
            board("https://pinterest.com/a/arte/", "Arte"),
            board("https://pinterest.com/a/fotografia/", "Fotografia"),
            board("https://pinterest.com/a/jardim/", "Jardim"),
        ]);
        selection
    }

    #[test]
    fn o_filtro_esconde_sem_escolher() {
        let mut selection = sample();
        selection.toggle("https://pinterest.com/a/arte/");
        selection.set_filter("jar");
        assert_eq!(selection.visible_count(), 1);
        // The board that is hidden keeps its choice.
        assert_eq!(selection.selected_count(), 1);
        assert!(selection.is_selected("https://pinterest.com/a/arte/"));
    }

    #[test]
    fn escolher_todos_escolhe_so_os_visiveis() {
        let mut selection = sample();
        selection.set_filter("a");
        selection.select_all_visible();
        assert_eq!(selection.selected_count(), 3);
        selection.set_filter("fotografia");
        selection.select_all_visible();
        assert_eq!(selection.selected_count(), 3);
    }

    #[test]
    fn uma_descoberta_nova_nao_joga_a_escolha_fora() {
        let mut selection = sample();
        selection.toggle("https://pinterest.com/a/arte/");
        selection.set_boards(vec![
            board("https://pinterest.com/a/arte/", "Arte"),
            board("https://pinterest.com/a/novo/", "Novo"),
        ]);
        assert_eq!(selection.selected_count(), 1);
        assert!(selection.is_selected("https://pinterest.com/a/arte/"));
        // A board that sumiu da lista nao fica escolhido.
        selection.set_boards(vec![board("https://pinterest.com/a/novo/", "Novo")]);
        assert_eq!(selection.selected_count(), 0);
    }

    #[test]
    fn a_escolha_vai_para_o_motor_na_ordem_da_lista() {
        let mut selection = sample();
        selection.toggle("https://pinterest.com/a/jardim/");
        selection.toggle("https://pinterest.com/a/arte/");
        assert_eq!(
            selection.selected_urls(),
            vec![
                "https://pinterest.com/a/arte/".to_string(),
                "https://pinterest.com/a/jardim/".to_string()
            ]
        );
    }

    #[test]
    fn o_filtro_olha_o_titulo_e_o_endereco() {
        let mut selection = sample();
        selection.set_filter("arte");
        assert_eq!(selection.visible_count(), 1);
        selection.set_filter("pinterest.com/a/jardim");
        assert_eq!(selection.visible_count(), 1);
        selection.set_filter("nada disso");
        assert_eq!(selection.visible_count(), 0);
    }
}
