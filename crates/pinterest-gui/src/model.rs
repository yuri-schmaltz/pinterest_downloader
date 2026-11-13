//! The state of the graphical interface.
//!
//! The journey has three steps and each one has its own state, so the
//! interface always says where it is: the profile, the choice of the boards
//! and the download. The state lives apart from the drawing, so the rules
//! can be tested without a screen.

use crate::boards::{BoardEntry, BoardSelection};
use crate::progress::ProgressModel;
use pinterest_core::engine::CollectionMode;
use std::path::PathBuf;

/// The three steps of the journey.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    /// The profile is being typed and discovered.
    Profile,
    /// The boards were found and the user chooses which ones to download.
    Boards,
    /// The download is running, or it already finished.
    Download,
}

impl Stage {
    /// The step that comes after this one.
    pub fn next(self) -> Option<Stage> {
        match self {
            Stage::Profile => Some(Stage::Boards),
            Stage::Boards => Some(Stage::Download),
            Stage::Download => None,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Stage::Profile => "Perfil",
            Stage::Boards => "Quadros",
            Stage::Download => "Download",
        }
    }

    /// The place of the step in the journey.
    ///
    /// The number is what the user sees in the circle of the step bar, and
    /// it is also o que diz se a etapa ja passou.
    pub fn index(self) -> usize {
        match self {
            Stage::Profile => 0,
            Stage::Boards => 1,
            Stage::Download => 2,
        }
    }
}

/// What the interface is doing right now.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Activity {
    /// Nothing is running.
    Idle,
    /// The profile is being discovered.
    Discovering,
    /// The download is running.
    Downloading,
}

impl Activity {
    pub fn is_running(self) -> bool {
        !matches!(self, Activity::Idle)
    }
}

/// The whole state of the interface.
#[derive(Debug, Clone)]
pub struct AppModel {
    pub stage: Stage,
    pub activity: Activity,
    pub target: String,
    pub boards: BoardSelection,
    pub progress: ProgressModel,
    pub out_root: PathBuf,
    pub workers: usize,
    pub max_pins: Option<usize>,
    pub mode: CollectionMode,
    /// The address the browser is asking the user to open.
    pub login_request: Option<String>,
    /// The last error, in a form the user can read.
    pub error: Option<String>,
    /// A short message about what just happened.
    pub notice: Option<String>,
}

impl Default for AppModel {
    fn default() -> Self {
        Self {
            stage: Stage::Profile,
            activity: Activity::Idle,
            target: String::new(),
            boards: BoardSelection::new(),
            progress: ProgressModel::new(500),
            out_root: PathBuf::from("downloads"),
            workers: 8,
            max_pins: None,
            mode: CollectionMode::Auto,
            login_request: None,
            error: None,
            notice: None,
        }
    }
}

impl AppModel {
    pub fn new() -> Self {
        Self::default()
    }

    /// Check the target before spending a browser on it.
    pub fn validate_target(&self) -> Result<String, String> {
        let target = self.target.trim();
        if target.is_empty() {
            return Err("Informe o usuario ou o endereco do perfil".into());
        }
        let looks_like_a_url = target.starts_with("http://") || target.starts_with("https://");
        if !looks_like_a_url {
            let valid = !target.is_empty()
                && target
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == '.');
            if !valid {
                return Err("O usuario so pode ter letras, numeros, ponto, traço e _. ".into());
            }
        }
        Ok(target.to_owned())
    }

    /// Start the discovery of the profile.
    pub fn begin_discovery(&mut self) -> Result<(), String> {
        if self.activity.is_running() {
            return Err("Ja existe uma operacao em andamento".into());
        }
        let target = self.validate_target()?;
        self.target = target;
        self.stage = Stage::Profile;
        self.activity = Activity::Discovering;
        self.error = None;
        self.notice = None;
        Ok(())
    }

    /// The discovery found the boards of the profile.
    pub fn boards_found(&mut self, boards: Vec<BoardEntry>) {
        self.boards.set_boards(boards);
        self.stage = Stage::Boards;
        self.activity = Activity::Idle;
        self.notice = Some(format!(
            "{} quadro(s) encontrado(s)",
            self.boards.boards().len()
        ));
    }

    /// The discovery failed.
    pub fn discovery_failed(&mut self, message: impl Into<String>) {
        self.activity = Activity::Idle;
        self.error = Some(message.into());
    }

    /// Start the download of the chosen boards.
    pub fn begin_download(&mut self) -> Result<Vec<String>, String> {
        if self.activity.is_running() {
            return Err("Ja existe uma operacao em andamento".into());
        }
        let urls = self.boards.selected_urls();
        if urls.is_empty() {
            return Err("Escolha ao menos um quadro".into());
        }
        self.stage = Stage::Download;
        self.activity = Activity::Downloading;
        self.error = None;
        self.notice = None;
        Ok(urls)
    }

    /// The download finished.
    pub fn download_finished(&mut self, cancelled: bool) {
        self.activity = Activity::Idle;
        if cancelled {
            self.notice = Some("Download cancelado; os arquivos ja prontos foram mantidos".into());
        }
    }

    /// The browser is asking the user to log in.
    pub fn login_requested(&mut self, url: impl Into<String>) {
        self.login_request = Some(url.into());
    }

    /// The login was answered.
    pub fn login_answered(&mut self) {
        self.login_request = None;
    }

    /// What the run is doing, in one line.
    ///
    /// The interface shows this next to the progress, para que o usuario
    /// saiba se o download ainda corre ou ja terminou.
    pub fn stage_state(&self) -> String {
        match self.activity {
            Activity::Discovering => "Procurando os quadros...".into(),
            Activity::Downloading => "Baixando as midias...".into(),
            Activity::Idle => {
                if self.progress.is_cancelled() {
                    "Cancelado; os arquivos ja prontos foram mantidos.".into()
                } else {
                    "Pronto.".into()
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn model(target: &str) -> AppModel {
        let mut model = AppModel::new();
        model.target = target.to_string();
        model
    }

    #[test]
    fn um_alvo_vazio_e_recusado() {
        assert!(model("").validate_target().is_err());
        assert!(model("   ").validate_target().is_err());
    }

    #[test]
    fn um_usuario_valido_e_aceito() {
        assert_eq!(model("alice").validate_target().unwrap(), "alice");
        assert_eq!(
            model("https://www.pinterest.com/alice/")
                .validate_target()
                .unwrap(),
            "https://www.pinterest.com/alice/"
        );
    }

    #[test]
    fn um_usuario_com_espaco_e_recusado() {
        assert!(model("alice smith").validate_target().is_err());
        assert!(model("alice/../outro").validate_target().is_err());
    }

    #[test]
    fn a_jornada_anda_um_passo_de_each_vez() {
        let mut model = AppModel::new();
        assert_eq!(model.stage, Stage::Profile);
        model.boards_found(vec![BoardEntry {
            url: "https://pinterest.com/a/arte/".into(),
            title: "Arte".into(),
            thumbnail_url: String::new(),
            pin_count: None,
        }]);
        assert_eq!(model.stage, Stage::Boards);
        model.boards.toggle("https://pinterest.com/a/arte/");
        model.begin_download().unwrap();
        assert_eq!(model.stage, Stage::Download);
        assert_eq!(model.activity, Activity::Downloading);
    }

    #[test]
    fn sem_escolha_nao_ha_download() {
        let mut model = AppModel::new();
        model.boards_found(vec![BoardEntry {
            url: "https://pinterest.com/a/arte/".into(),
            title: "Arte".into(),
            thumbnail_url: String::new(),
            pin_count: None,
        }]);
        assert!(model.begin_download().is_err());
    }

    #[test]
    fn duas_operacoes_ao_mesmo_tempo_sao_recusadas() {
        let mut model = model("alice");
        model.begin_discovery().unwrap();
        assert!(model.begin_discovery().is_err());
        model.discovery_failed("deu ruim");
        assert_eq!(model.activity, Activity::Idle);
        assert_eq!(model.error.as_deref(), Some("deu ruim"));
    }

    #[test]
    fn o_login_pendente_some_quando_e_respondido() {
        let mut model = AppModel::new();
        model.login_requested("https://www.pinterest.com/alice/");
        assert!(model.login_request.is_some());
        model.login_answered();
        assert!(model.login_request.is_none());
    }
}
