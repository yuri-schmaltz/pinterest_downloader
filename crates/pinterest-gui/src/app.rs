//! The window of the graphical interface.
//!
//! The interface has three steps: the profile, the choice of the boards and
//! the download. The download runs on a background runtime and never on the
//! thread that draws the interface, so the window stays responsive.

use crate::boards::BoardEntry;
use crate::model::{Activity, AppModel, Stage};
use crate::progress::LogLevel;
use crate::theme;
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
    /// The folder where the files are written, as the user types it.
    pub out_root_text: String,
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
            out_root_text: String::new(),
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
        theme::apply(ctx);

        self.steps_bar(ctx);
        self.error_bar(ctx);

        // The footer comes first: the panel do meio so sabe o espaco que
        // sobrou, e o cartao nao invade a barra de baixo.
        self.footer(ctx);

        egui::CentralPanel::default()
            .frame(
                egui::Frame::new()
                    .fill(theme::BG)
                    .inner_margin(egui::Margin::symmetric(18, 12)),
            )
            .show(ctx, |ui| {
                theme::card(ui, |ui| match self.model.stage {
                    Stage::Profile => self.profile(ui),
                    Stage::Boards => self.boards(ui),
                    Stage::Download => self.download(ui),
                });
            });

        self.login_dialog(ctx);
    }

    /// The bar at the top: the steps, the profile and the state of the run.
    ///
    /// The profile stays in this bar in every step, como na interface em
    /// PyQt6: o usuario ve o que esta baixando sem precisar voltar.
    fn steps_bar(&mut self, ctx: &egui::Context) {
        egui::TopBottomPanel::top("steps")
            .exact_height(66.0)
            .frame(
                egui::Frame::new()
                    .fill(theme::SURFACE)
                    .inner_margin(egui::Margin::symmetric(22, 14)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    let current = self.model.stage.index();
                    // The steps take a fixed width, so the profile and the
                    // state of the run always find room on the right.
                    ui.allocate_ui_with_layout(
                        egui::vec2(392.0, ui.available_height()),
                        egui::Layout::left_to_right(egui::Align::Center),
                        |ui| {
                            for (index, stage) in [Stage::Profile, Stage::Boards, Stage::Download]
                                .into_iter()
                                .enumerate()
                            {
                                if index > 0 {
                                    theme::step_line(ui);
                                    ui.add_space(14.0);
                                }
                                let state = if index == current {
                                    theme::StepState::Active
                                } else if index < current {
                                    theme::StepState::Done
                                } else {
                                    theme::StepState::Pending
                                };
                                theme::step_badge(ui, &(index + 1).to_string(), state);
                                ui.add_space(9.0);
                                let color = match state {
                                    theme::StepState::Active => theme::TEXT,
                                    theme::StepState::Done => theme::GREEN,
                                    theme::StepState::Pending => theme::TEXT_MUTED,
                                };
                                let text = self.label(stage.label());
                                ui.label(egui::RichText::new(text).color(color).strong());
                                ui.add_space(18.0);
                            }
                        },
                    );

                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        let status = self.status_line();
                        ui.colored_label(theme::TEXT_MUTED, status);
                        ui.add_space(20.0);
                        let response = theme::field(
                            ui,
                            &mut self.model.target,
                            "usuario ou https://www.pinterest.com/usuario/",
                            280.0,
                        );
                        // The field keeps the focus, so the user can
                        // press Enter to start the search.
                        if response.lost_focus()
                            && ui.input(|input| input.key_pressed(egui::Key::Enter))
                        {
                            self.start_discovery();
                        }
                    });
                });
            });
    }

    /// The bar that shows an error, when there is one.
    fn error_bar(&mut self, ctx: &egui::Context) {
        let Some(error) = self.model.error.clone() else {
            return;
        };
        egui::TopBottomPanel::top("error")
            .frame(
                egui::Frame::new()
                    .fill(theme::BG)
                    .inner_margin(egui::Margin::symmetric(22, 8)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    let text = self.label(format!("Erro: {error}"));
                    ui.colored_label(theme::ERROR, text);
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if theme::button(ui, "Fechar", theme::ButtonKind::Quiet) {
                            self.model.error = None;
                        }
                    });
                });
            });
    }

    /// The bar at the bottom: what the run is doing and what can be done.
    fn footer(&mut self, ctx: &egui::Context) {
        egui::TopBottomPanel::bottom("footer")
            .exact_height(64.0)
            .frame(
                egui::Frame::new()
                    .fill(theme::SURFACE)
                    .inner_margin(egui::Margin::symmetric(22, 14)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    let summary = self.footer_summary();
                    ui.colored_label(theme::TEXT_MUTED, summary);
                    ui.with_layout(
                        egui::Layout::right_to_left(egui::Align::Center),
                        |ui| match self.model.stage {
                            Stage::Profile => {}
                            Stage::Boards => {
                                let text = self.label("Baixar escolhidos");
                                let running = self.model.activity.is_running();
                                let enabled = !running && self.model.boards.selected_count() > 0;
                                if theme::button_enabled(
                                    ui,
                                    &text,
                                    theme::ButtonKind::Primary,
                                    enabled,
                                ) {
                                    self.start_download();
                                }
                                ui.add_space(10.0);
                                let back = self.label("Voltar");
                                if theme::button(ui, &back, theme::ButtonKind::Quiet) {
                                    self.model.stage = Stage::Profile;
                                }
                            }
                            Stage::Download => {
                                if self.model.activity.is_running() {
                                    let text = self.label("Cancelar");
                                    if theme::button(ui, &text, theme::ButtonKind::Danger) {
                                        self.cancel();
                                    }
                                } else {
                                    let back = self.label("Voltar aos quadros");
                                    if theme::button(ui, &back, theme::ButtonKind::Quiet) {
                                        self.model.stage = Stage::Boards;
                                    }
                                }
                            }
                        },
                    );
                });
            });
    }

    /// What the interface says about the run, in one line.
    fn status_line(&self) -> String {
        if let Some(notice) = &self.model.notice {
            return notice.clone();
        }
        match self.model.activity {
            Activity::Discovering => "Procurando os quadros...".to_owned(),
            Activity::Downloading => "Baixando as midias...".to_owned(),
            Activity::Idle => "Pronto.".to_owned(),
        }
    }

    /// What the footer says about the step the user is on.
    fn footer_summary(&self) -> String {
        match self.model.stage {
            Stage::Profile => "Escreva o perfil e procure os quadros.".to_owned(),
            Stage::Boards => format!(
                "{} de {} quadro(s) escolhido(s).",
                self.model.boards.selected_count(),
                self.model.boards.boards().len()
            ),
            Stage::Download => {
                let totals = self.model.progress.totals();
                format!(
                    "Novos: {}  ·  Reutilizados: {}  ·  Falhas: {}",
                    totals.downloaded, totals.reused, totals.failed
                )
            }
        }
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
        theme::step_title(ui, &self.label("De qual perfil do Pinterest?"));
        ui.add_space(6.0);
        theme::hint(
            ui,
            "Escreva o usuario ou a URL do perfil no campo acima, a direita. As duas formas valem.",
        );
        ui.add_space(20.0);

        let running = self.model.activity == Activity::Discovering;
        ui.horizontal(|ui| {
            let text = self.label("Buscar quadros");
            if theme::button_enabled(ui, &text, theme::ButtonKind::Secondary, !running) {
                self.start_discovery();
            }
            if running {
                ui.add_space(12.0);
                ui.spinner();
                ui.label(egui::RichText::new("Procurando os quadros...").color(theme::TEXT_MUTED));
            }
        });

        if let Some(notice) = self.model.notice.clone() {
            ui.add_space(16.0);
            theme::quiet(ui, notice);
        }
    }

    fn boards(&mut self, ui: &mut egui::Ui) {
        theme::step_title(ui, &self.label("Escolha os quadros que quer baixar"));
        ui.add_space(12.0);

        // The filter and the quick choices.
        ui.horizontal(|ui| {
            theme::field(ui, &mut self.filter, "Buscar quadro...", 240.0);
            if theme::button(ui, "Filtrar", theme::ButtonKind::Quiet) {
                self.model.boards.set_filter(self.filter.clone());
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let none = self.label("Escolher nenhum");
                if theme::button(ui, &none, theme::ButtonKind::Quiet) {
                    self.model.boards.clear_selection();
                }
                ui.add_space(8.0);
                let all = self.label("Escolher todos");
                if theme::button(ui, &all, theme::ButtonKind::Quiet) {
                    self.model.boards.select_all_visible();
                }
            });
        });
        ui.add_space(14.0);

        // The list is copied before the drawing: the drawing records what
        // it shows and cannot hold a borrow of the model while it does so.
        let visible: Vec<(String, String, Option<u64>)> = self
            .model
            .boards
            .visible()
            .into_iter()
            .map(|board| (board.url.clone(), board.title.clone(), board.pin_count))
            .collect();
        if visible.is_empty() {
            theme::hint(ui, "Nenhum quadro carregado.");
            return;
        }

        let mut chosen = Vec::new();
        // The grid is as wide as the card allows; each cover fills its own
        // column, so the row of covers has no gap in the middle.
        let cell = 150.0;
        let spacing = 16.0;
        let columns = ((ui.available_width() + spacing) / (cell + spacing))
            .floor()
            .max(1.0) as usize;
        egui::ScrollArea::vertical()
            .max_height(392.0)
            .show(ui, |ui| {
                ui.columns(columns, |columns_ui| {
                    // The width of one column is the width of the cover.
                    let side = columns_ui[0].available_width().clamp(96.0, 210.0);
                    for (index, (url, title, pin_count)) in visible.iter().enumerate() {
                        let column = index % columns;
                        let column_ui = &mut columns_ui[column];
                        let mut selected = self.model.boards.is_selected(url);
                        let handle = self.thumbnails.get(url).cloned();

                        column_ui.vertical(|ui| {
                            let (rect, _) = ui
                                .allocate_exact_size(egui::vec2(side, side), egui::Sense::hover());
                            match handle {
                                Some(handle) => {
                                    let mut image = egui::Image::new(&handle);
                                    image = image.fit_to_exact_size(egui::vec2(side, side));
                                    image.paint_at(ui, rect);
                                }
                                None => {
                                    // A square placeholder, so the grid keeps
                                    // its shape while the cover is on its way.
                                    ui.painter().rect_filled(rect, 8.0, theme::SURFACE_2);
                                    ui.painter().rect_stroke(
                                        rect,
                                        8.0,
                                        egui::Stroke::new(1.0_f32, theme::BORDER),
                                        egui::StrokeKind::Inside,
                                    );
                                    ui.painter().text(
                                        rect.center(),
                                        egui::Align2::CENTER_CENTER,
                                        "…",
                                        egui::FontId::new(18.0, egui::FontFamily::Proportional),
                                        theme::TEXT_DIM,
                                    );
                                }
                            }
                            ui.add_space(6.0);
                            ui.horizontal(|ui| {
                                if ui.checkbox(&mut selected, "").changed() {
                                    chosen.push((url.clone(), selected));
                                }
                                ui.vertical(|ui| {
                                    let shown = self.label(title.clone());
                                    ui.add(
                                        egui::Label::new(
                                            egui::RichText::new(shown).strong().color(theme::TEXT),
                                        )
                                        .truncate(),
                                    );
                                    if let Some(count) = pin_count {
                                        theme::quiet(ui, format!("{count} pins"));
                                    }
                                });
                            });
                        });
                    }
                });
            });
        for (url, selected) in chosen {
            self.model.boards.toggle(&url);
            if selected != self.model.boards.is_selected(&url) {
                // Keep the model in step with what the user clicked.
                self.model.boards.toggle(&url);
            }
        }

        ui.add_space(14.0);
        self.options_strip(ui);
    }

    /// The strip with the destination and the adjustments of the run.
    fn options_strip(&mut self, ui: &mut egui::Ui) {
        egui::Frame::new()
            .fill(theme::SURFACE_2)
            .stroke(egui::Stroke::new(1.0_f32, theme::BORDER))
            .corner_radius(egui::CornerRadius::same(theme::RADIUS_CARD))
            .inner_margin(egui::Margin::symmetric(14, 10))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    theme::quiet(ui, "Destino");
                    let mut out_root = self.out_root_text.clone();
                    let response = theme::field(ui, &mut out_root, "pasta de destino", 280.0);
                    if response.changed() {
                        self.out_root_text = out_root.clone();
                        self.model.out_root = std::path::PathBuf::from(&out_root);
                    }
                    ui.add_space(24.0);
                    theme::quiet(ui, "Workers");
                    ui.add(
                        egui::DragValue::new(&mut self.model.workers)
                            .range(1..=32)
                            .speed(1),
                    );
                    ui.add_space(24.0);
                    theme::quiet(ui, "Modo");
                    let mut mode = self.model.mode;
                    egui::ComboBox::from_id_salt("modo")
                        .selected_text(match mode {
                            pinterest_core::engine::CollectionMode::Auto => "Automatico",
                            pinterest_core::engine::CollectionMode::Browser => "Browser",
                            pinterest_core::engine::CollectionMode::Http => "HTTP",
                        })
                        .show_ui(ui, |ui| {
                            for option in [
                                pinterest_core::engine::CollectionMode::Auto,
                                pinterest_core::engine::CollectionMode::Browser,
                                pinterest_core::engine::CollectionMode::Http,
                            ] {
                                let text = match option {
                                    pinterest_core::engine::CollectionMode::Auto => "Automatico",
                                    pinterest_core::engine::CollectionMode::Browser => "Browser",
                                    pinterest_core::engine::CollectionMode::Http => "HTTP",
                                };
                                ui.selectable_value(&mut mode, option, text);
                            }
                        });
                    self.model.mode = mode;
                });
            });
    }

    fn download(&mut self, ui: &mut egui::Ui) {
        theme::step_title(ui, &self.label("Download"));
        ui.add_space(12.0);

        // The progress card.
        let (current, total) = {
            let progress = &self.model.progress;
            (progress.current(), progress.total())
        };
        egui::Frame::new()
            .fill(theme::SURFACE_2)
            .stroke(egui::Stroke::new(1.0_f32, theme::BORDER))
            .corner_radius(egui::CornerRadius::same(theme::RADIUS_CARD))
            .inner_margin(egui::Margin::symmetric(14, 12))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    let ratio = if total > 0 {
                        current as f32 / total as f32
                    } else {
                        0.0
                    };
                    theme::progress_bar(ui, ratio, &format!("{current}/{total}"), 340.0);
                    ui.add_space(18.0);
                    if self.model.activity.is_running() {
                        ui.spinner();
                    }
                    let state = self.model.stage_state();
                    theme::quiet(ui, state);
                });
            });
        ui.add_space(12.0);

        // The totals.
        let totals = self.model.progress.totals().clone();
        ui.horizontal(|ui| {
            let novos = format!("Novos: {}", totals.downloaded);
            let reutilizados = format!("Reutilizados: {}", totals.reused);
            let falhas = format!("Falhas: {}", totals.failed);
            ui.label(self.label(novos));
            ui.label(self.label(reutilizados));
            ui.label(self.label(falhas));
        });
        ui.add_space(12.0);

        // The log.
        egui::Frame::new()
            .fill(theme::SURFACE)
            .stroke(egui::Stroke::new(1.0_f32, theme::BORDER))
            .corner_radius(egui::CornerRadius::same(theme::RADIUS_CARD))
            .inner_margin(egui::Margin::symmetric(14, 10))
            .show(ui, |ui| {
                theme::quiet(ui, "Registro");
                ui.add_space(4.0);
                let lines: Vec<(LogLevel, String)> = self
                    .model
                    .progress
                    .logs()
                    .iter()
                    .map(|line| (line.level, line.message.clone()))
                    .collect();
                egui::ScrollArea::vertical()
                    .max_height(240.0)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for (level, message) in lines {
                            let color = match level {
                                LogLevel::Info => theme::TEXT_MUTED,
                                LogLevel::Warning => theme::WARNING,
                                LogLevel::Error => theme::ERROR,
                            };
                            ui.label(egui::RichText::new(message).monospace().color(color));
                        }
                    });
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
