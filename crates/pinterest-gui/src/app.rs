//! The window of the graphical interface.
//!
//! The interface has three steps: the profile, the choice of the boards and
//! the download. The download runs on a background runtime and never on the
//! thread that draws the interface, so the window stays responsive.

use crate::boards::BoardEntry;
use crate::model::{Activity, AppModel, Stage};
use crate::progress::LogLevel;
use crate::thumbs::ThumbnailCache;
use eframe::egui;
use pinterest_core::engine::{self, RunOptions};
use pinterest_core::runtime::{Operation, RunEvent, RunTotals};
use pinterest_core::{BoardMetadata, DownloadOptions};
use std::collections::{HashMap, HashSet};
use std::io::Read;
use std::sync::mpsc::{Receiver, Sender, TryRecvError};
use std::sync::{Arc, Mutex};

/// What the background task sends to the interface.
pub enum Message {
    /// The profile was discovered.
    Boards(Vec<BoardMetadata>),
    /// An event of the engine.
    Event(RunEvent),
    /// The operation ended.
    Finished(Result<(), String>),
    /// The browser is asking the user to log in.
    Login(String),
    /// The cover of a board arrived.
    Thumbnail(String, Option<Vec<u8>>),
}

pub struct App {
    pub model: AppModel,
    pub messages: Receiver<Message>,
    pub sender: Sender<Message>,
    /// The operation of the run in progress, so that it can be cancelled.
    pub operation: Arc<Mutex<Option<Operation>>>,
    /// The cover of each board, with a limit on how many are kept.
    pub thumbnails: ThumbnailCache<egui::TextureHandle>,
    /// The covers that arrived and still wait for a texture.
    pending_images: HashMap<String, egui::ColorImage>,
    /// The boards whose cover is being fetched.
    pending_thumbnails: HashSet<String>,
    /// The runtime that runs the engine in the background.
    pub runtime: Option<tokio::runtime::Runtime>,
    pub filter: String,
    /// The texts the last frame showed.
    ///
    /// The drawing is the only place that knows what the user reads, so it
    /// is also the place that records it. A test checks these texts without
    /// a screen.
    pub last_labels: Vec<String>,
}

impl App {
    pub fn new() -> Self {
        let (sender, messages) = std::sync::mpsc::channel();
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .ok();
        Self {
            model: AppModel::new(),
            messages,
            sender,
            operation: Arc::new(Mutex::new(None)),
            thumbnails: ThumbnailCache::new(120),
            pending_images: HashMap::new(),
            pending_thumbnails: HashSet::new(),
            runtime,
            filter: String::new(),
            last_labels: Vec::new(),
        }
    }

    /// The options the engine runs with.
    pub fn run_options(&self) -> RunOptions {
        RunOptions {
            download: DownloadOptions {
                out_root: self.model.out_root.clone(),
                workers: self.model.workers,
                rate_limiting: true,
                max_pins: self.model.max_pins,
                ..Default::default()
            },
            mode: self.model.mode,
            ..Default::default()
        }
    }

    pub fn start_discovery(&mut self) {
        if let Err(message) = self.model.begin_discovery() {
            self.model.discovery_failed(message);
            return;
        }
        let Some(runtime) = self.runtime.as_ref() else {
            self.model
                .discovery_failed("Nao foi possivel iniciar o motor da interface");
            return;
        };
        let target = self.model.target.clone();
        let options = self.run_options();
        let (operation, mut events) = Operation::new(512);
        if let Ok(mut guard) = self.operation.lock() {
            *guard = Some(operation.clone());
        }
        let sender = self.sender.clone();
        runtime.spawn(async move {
            let pump_sender = sender.clone();
            let pump = tokio::spawn(async move {
                while let Some(envelope) = events.recv().await {
                    let event = envelope.event;
                    if let RunEvent::LoginRequired { url } = &event {
                        let _ = pump_sender.send(Message::Login(url.clone()));
                    }
                    if pump_sender.send(Message::Event(event)).is_err() {
                        break;
                    }
                }
            });
            let result = engine::discover_boards(&target, options, operation.clone()).await;
            match result {
                Ok(discovered) => {
                    let _ = sender.send(Message::Boards(discovered.boards));
                }
                Err(error) => {
                    let _ =
                        sender.send(Message::Finished(Err(engine::public_error_message(&error))));
                }
            }
            pump.abort();
            let _ = sender.send(Message::Finished(Ok(())));
        });
    }

    pub fn start_download(&mut self) {
        let boards = match self.model.begin_download() {
            Ok(boards) => boards,
            Err(message) => {
                self.model.error = Some(message);
                return;
            }
        };
        let Some(runtime) = self.runtime.as_ref() else {
            self.model
                .discovery_failed("Nao foi possivel iniciar o motor da interface");
            return;
        };
        let options = self.run_options();
        let (operation, mut events) = Operation::new(512);
        if let Ok(mut guard) = self.operation.lock() {
            *guard = Some(operation.clone());
        }
        let sender = self.sender.clone();
        runtime.spawn(async move {
            let pump_sender = sender.clone();
            let pump = tokio::spawn(async move {
                while let Some(envelope) = events.recv().await {
                    let event = envelope.event;
                    if let RunEvent::LoginRequired { url } = &event {
                        let _ = pump_sender.send(Message::Login(url.clone()));
                    }
                    if pump_sender.send(Message::Event(event)).is_err() {
                        break;
                    }
                }
            });
            let result = engine::run_boards(boards, options, operation.clone()).await;
            let message = match result {
                Ok(report) => {
                    let totals: RunTotals = report.totals;
                    let _ = sender.send(Message::Event(RunEvent::Finished { totals }));
                    Ok(())
                }
                Err(error) => Err(engine::public_error_message(&error)),
            };
            pump.abort();
            let _ = sender.send(Message::Finished(message));
        });
    }

    /// Ask for the covers of the boards that are visible and still missing.
    ///
    /// Only a few covers are fetched at a time: a profile can have hundreds
    /// of boards and downloading all of them at once would make the list
    /// slow before the user even sees it.
    pub fn request_thumbnails(&mut self) {
        let wanted: Vec<(String, String)> = self
            .model
            .boards
            .visible()
            .into_iter()
            .filter(|board| !board.thumbnail_url.is_empty())
            .map(|board| (board.url.clone(), board.thumbnail_url.clone()))
            .collect();
        for (url, thumbnail) in wanted {
            if self.thumbnails.contains(&url) || self.pending_thumbnails.contains(&url) {
                continue;
            }
            if self.pending_thumbnails.len() >= 8 {
                break;
            }
            self.pending_thumbnails.insert(url.clone());
            let Some(runtime) = self.runtime.as_ref() else {
                continue;
            };
            let sender = self.sender.clone();
            runtime.spawn(async move {
                let bytes = fetch_bytes(&thumbnail).await;
                let _ = sender.send(Message::Thumbnail(url, bytes));
            });
        }
    }

    /// Turn the covers that arrived into textures.
    pub fn load_pending_images(&mut self, ctx: &egui::Context) {
        if self.pending_images.is_empty() {
            return;
        }
        let images = std::mem::take(&mut self.pending_images);
        for (url, image) in images {
            let handle =
                ctx.load_texture(format!("capa-{url}"), image, egui::TextureOptions::LINEAR);
            self.thumbnails.insert(url, handle);
        }
    }

    pub fn cancel(&mut self) {
        if let Ok(mut guard) = self.operation.lock() {
            if let Some(operation) = guard.take() {
                operation.cancel();
            }
        }
        self.model.download_finished(true);
    }

    /// Take the messages the background task sent.
    pub fn drain(&mut self) {
        loop {
            match self.messages.try_recv() {
                Ok(Message::Boards(boards)) => {
                    let entries: Vec<BoardEntry> = boards.iter().map(BoardEntry::from).collect();
                    self.model.boards_found(entries);
                }
                Ok(Message::Event(event)) => {
                    self.model.progress.apply(&event);
                    match &event {
                        RunEvent::CollectionFinished { count, .. } => {
                            self.model.progress.push(
                                LogLevel::Info,
                                format!("Coleta terminou com {count} pin(s)"),
                            );
                        }
                        RunEvent::Warning { message } => {
                            self.model.progress.push(LogLevel::Warning, message.clone());
                        }
                        RunEvent::Failed { message, .. } => {
                            self.model.progress.push(LogLevel::Error, message.clone());
                        }
                        _ => {}
                    }
                }
                Ok(Message::Finished(result)) => {
                    let cancelled = self.model.progress.is_cancelled();
                    match result {
                        Ok(()) => self.model.download_finished(cancelled),
                        Err(message) => {
                            self.model.error = Some(message);
                            self.model.activity = Activity::Idle;
                        }
                    }
                }
                Ok(Message::Login(url)) => self.model.login_requested(url),
                Ok(Message::Thumbnail(url, bytes)) => {
                    self.pending_thumbnails.remove(&url);
                    if let Some(bytes) = bytes {
                        if let Some(image) = decode_image(&bytes) {
                            self.pending_images.insert(url, image);
                        }
                    }
                }
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => break,
            }
        }
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.update_ui(ctx);
    }
}

impl Default for App {
    fn default() -> Self {
        Self::new()
    }
}

impl App {
    /// Record a text that the interface shows.
    fn label(&mut self, text: impl Into<String>) -> String {
        let text = text.into();
        self.last_labels.push(text.clone());
        text
    }

    /// Draw one frame.
    ///
    /// The method does not need a window, so the interface can be drawn in
    /// a test without a screen.
    pub fn update_ui(&mut self, ctx: &egui::Context) {
        self.last_labels.clear();
        self.drain();
        self.load_pending_images(ctx);
        if self.model.stage == Stage::Boards {
            self.request_thumbnails();
        }
        ctx.set_theme(egui::Theme::Dark);

        egui::TopBottomPanel::top("steps").show(ctx, |ui| {
            ui.add_space(6.0);
            ui.horizontal(|ui| {
                ui.heading("Pinterest Board Downloader");
                ui.separator();
                for stage in [Stage::Profile, Stage::Boards, Stage::Download] {
                    let active = self.model.stage == stage;
                    let text = if active {
                        format!("● {}", stage.label())
                    } else {
                        format!("○ {}", stage.label())
                    };
                    if active {
                        ui.label(egui::RichText::new(text).strong());
                    } else {
                        ui.label(text);
                    }
                }
            });
            ui.add_space(4.0);
        });

        if let Some(error) = self.model.error.clone() {
            egui::TopBottomPanel::top("error").show(ctx, |ui| {
                ui.horizontal(|ui| {
                    let text = self.label(format!("Erro: {error}"));
                    ui.colored_label(egui::Color32::from_rgb(240, 120, 120), text);
                    if ui.button("Fechar").clicked() {
                        self.model.error = None;
                    }
                });
            });
        }

        egui::CentralPanel::default().show(ctx, |ui| match self.model.stage {
            Stage::Profile => self.profile(ui),
            Stage::Boards => self.boards(ui),
            Stage::Download => self.download(ui),
        });

        self.login_dialog(ctx);
    }
}

/// Download the bytes of an image.
async fn fetch_bytes(url: &str) -> Option<Vec<u8>> {
    let agent = ureq::Agent::new();
    let response = agent.get(url).call().ok()?;
    let mut buffer = Vec::new();
    response.into_reader().read_to_end(&mut buffer).ok()?;
    Some(buffer)
}

/// Turn the bytes of an image into something the interface can draw.
fn decode_image(bytes: &[u8]) -> Option<egui::ColorImage> {
    let image = image::load_from_memory(bytes).ok()?.to_rgba8();
    let (width, height) = (image.width() as usize, image.height() as usize);
    Some(egui::ColorImage::from_rgba_unmultiplied(
        [width, height],
        image.as_raw(),
    ))
}

impl App {
    fn profile(&mut self, ui: &mut egui::Ui) {
        ui.add_space(10.0);
        ui.heading(self.label("Perfil"));
        ui.label("Informe o usuario do Pinterest ou o endereco do perfil.");
        ui.horizontal(|ui| {
            let response = ui.add(
                egui::TextEdit::singleline(&mut self.model.target)
                    .hint_text("usuario ou https://www.pinterest.com/usuario/")
                    .desired_width(420.0),
            );
            // The field keeps the focus, so the user can press Enter.
            if response.lost_focus() && ui.input(|input| input.key_pressed(egui::Key::Enter)) {
                self.start_discovery();
            }
            let running = self.model.activity == Activity::Discovering;
            let text = self.label("Buscar quadros");
            if ui.add_enabled(!running, egui::Button::new(text)).clicked() {
                self.start_discovery();
            }
            if running {
                ui.spinner();
            }
        });
        if let Some(notice) = &self.model.notice {
            ui.label(notice);
        }
    }

    fn boards(&mut self, ui: &mut egui::Ui) {
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            ui.heading(self.label("Quadros"));
            ui.separator();
            ui.label(format!(
                "{} de {} escolhido(s)",
                self.model.boards.selected_count(),
                self.model.boards.boards().len()
            ));
            ui.text_edit_singleline(&mut self.filter);
            if ui.button("Filtrar").clicked() {
                self.model.boards.set_filter(self.filter.clone());
            }
            if ui.button("Escolher todos").clicked() {
                self.model.boards.select_all_visible();
            }
            if ui.button("Escolher nenhum").clicked() {
                self.model.boards.clear_selection();
            }
        });
        ui.separator();

        // The list is copied before the drawing: the drawing records what
        // it shows and cannot hold a borrow of the model while it does so.
        let visible: Vec<(String, String, Option<u64>)> = self
            .model
            .boards
            .visible()
            .into_iter()
            .map(|board| (board.url.clone(), board.title.clone(), board.pin_count))
            .collect();
        let mut chosen = Vec::new();
        egui::ScrollArea::vertical().show(ui, |ui| {
            for (url, title, pin_count) in visible {
                let mut selected = self.model.boards.is_selected(&url);
                ui.horizontal(|ui| {
                    if ui.checkbox(&mut selected, "").changed() {
                        chosen.push((url.clone(), selected));
                    }
                    ui.add_space(8.0);
                    // The cover is square, so it does not distort.
                    let side = egui::vec2(56.0, 56.0);
                    match self.thumbnails.get(&url) {
                        Some(handle) => {
                            ui.add(egui::Image::new(handle).fit_to_exact_size(side));
                        }
                        None => {
                            // A square placeholder, so the list keeps its
                            // shape while the cover is on its way.
                            let (rect, _) = ui.allocate_exact_size(side, egui::Sense::hover());
                            ui.painter()
                                .rect_filled(rect, 2.0, ui.visuals().extreme_bg_color);
                        }
                    }
                    let shown = self.label(title.clone());
                    ui.vertical(|ui| {
                        ui.label(egui::RichText::new(shown).strong());
                        if let Some(count) = pin_count {
                            ui.small(format!("{count} pins"));
                        }
                        ui.small(&url);
                    });
                });
            }
        });
        for (url, selected) in chosen {
            self.model.boards.toggle(&url);
            if selected != self.model.boards.is_selected(&url) {
                // Keep the model in step with what the user clicked.
                self.model.boards.toggle(&url);
            }
        }

        ui.separator();
        ui.horizontal(|ui| {
            if ui.button("Voltar").clicked() {
                self.model.stage = Stage::Profile;
            }
            let running = self.model.activity.is_running();
            let text = self.label("Baixar escolhidos");
            if ui
                .add_enabled(
                    !running && self.model.boards.selected_count() > 0,
                    egui::Button::new(text),
                )
                .clicked()
            {
                self.start_download();
            }
            ui.label(format!("Workers: {}", self.model.workers));
        });
    }

    fn download(&mut self, ui: &mut egui::Ui) {
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            ui.heading(self.label("Download"));
            ui.separator();
            let progress = &self.model.progress;
            let current = progress.current();
            let total = progress.total();
            ui.add(
                egui::ProgressBar::new(if total > 0 {
                    current as f32 / total as f32
                } else {
                    0.0
                })
                .desired_width(320.0)
                .text(format!("{current}/{total}")),
            );
            if self.model.activity.is_running() {
                let text = self.label("Cancelar");
                if ui.button(text).clicked() {
                    self.cancel();
                }
            } else if ui.button("Voltar aos quadros").clicked() {
                self.model.stage = Stage::Boards;
            }
        });
        ui.separator();

        egui::ScrollArea::vertical()
            .max_height(220.0)
            .show(ui, |ui| {
                for line in self.model.progress.logs() {
                    let color = match line.level {
                        LogLevel::Info => egui::Color32::LIGHT_GRAY,
                        LogLevel::Warning => egui::Color32::from_rgb(240, 200, 120),
                        LogLevel::Error => egui::Color32::from_rgb(240, 120, 120),
                    };
                    ui.colored_label(color, &line.message);
                }
            });

        ui.separator();
        let totals = self.model.progress.totals().clone();
        ui.horizontal(|ui| {
            let novos = format!("Novos: {}", totals.downloaded);
            let reutilizados = format!("Reutilizados: {}", totals.reused);
            let falhas = format!("Falhas: {}", totals.failed);
            ui.label(self.label(novos));
            ui.label(self.label(reutilizados));
            ui.label(self.label(falhas));
        });
    }

    /// The dialog that asks the user to log in.
    fn login_dialog(&mut self, ctx: &egui::Context) {
        let Some(url) = self.model.login_request.clone() else {
            return;
        };
        let mut open = true;
        let mut resume = false;
        let mut cancel = false;
        egui::Window::new("Login necessario")
            .collapsible(false)
            .resizable(false)
            .open(&mut open)
            .show(ctx, |ui| {
                ui.label(format!("Faca login no browser para {url}."));
                ui.label("Depois de logar, volte para aqui e continue.");
                ui.horizontal(|ui| {
                    let continuar = self.label("Continuar");
                    if ui.button(continuar).clicked() {
                        resume = true;
                    }
                    let cancelar = self.label("Cancelar");
                    if ui.button(cancelar).clicked() {
                        cancel = true;
                    }
                });
            });
        if resume {
            if let Ok(guard) = self.operation.lock() {
                if let Some(operation) = guard.as_ref() {
                    operation.resume_login();
                }
            }
            self.model.login_answered();
        }
        if cancel {
            self.cancel();
            self.model.login_answered();
        }
    }
}
