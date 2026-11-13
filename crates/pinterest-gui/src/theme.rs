//! The look of the interface: colors, spacing and the small pieces.
//!
//! The interface em PyQt6 tem uma folha de estilo escura; aqui a mesma
//! paleta e aplicada no egui, para que as duas ferramentas tenham a mesma
//! cara. Sem este modulo o egui desenha os botoes e os campos do jeito
//! dele, e a janela fica com aparencia de ferramenta em vez de produto.

use eframe::egui;

/// The background of the window.
pub const BG: egui::Color32 = egui::Color32::from_rgb(0x1A, 0x1D, 0x23);
/// The surface of a card, of the steps bar and of the footer.
pub const SURFACE: egui::Color32 = egui::Color32::from_rgb(0x22, 0x26, 0x2E);
/// A surface a little lighter, for the fields.
pub const SURFACE_2: egui::Color32 = egui::Color32::from_rgb(0x2A, 0x2F, 0x38);
/// A surface a little lighter still, for the hover.
pub const SURFACE_3: egui::Color32 = egui::Color32::from_rgb(0x3A, 0x41, 0x4D);
/// The quiet border of a card.
pub const BORDER: egui::Color32 = egui::Color32::from_rgb(0x31, 0x36, 0x40);
/// The border of a field.
pub const BORDER_STRONG: egui::Color32 = egui::Color32::from_rgb(0x3A, 0x41, 0x4D);
/// The text the user reads first.
pub const TEXT: egui::Color32 = egui::Color32::from_rgb(0xE6, 0xE8, 0xEC);
/// The text that explains.
pub const TEXT_MUTED: egui::Color32 = egui::Color32::from_rgb(0x9A, 0xA1, 0xAC);
/// The text that cannot be used.
pub const TEXT_DIM: egui::Color32 = egui::Color32::from_rgb(0x6B, 0x72, 0x80);
/// The color of the brand, and the color of the main action.
pub const ACCENT: egui::Color32 = egui::Color32::from_rgb(0xE6, 0x00, 0x23);
pub const ACCENT_HOVER: egui::Color32 = egui::Color32::from_rgb(0xFF, 0x2E, 0x4D);
pub const ACCENT_ACTIVE: egui::Color32 = egui::Color32::from_rgb(0xC4, 0x00, 0x1D);
/// The secondary action.
pub const BLUE: egui::Color32 = egui::Color32::from_rgb(0x00, 0x76, 0xD3);
pub const BLUE_HOVER: egui::Color32 = egui::Color32::from_rgb(0x2E, 0x8F, 0xE8);
/// A link, and the text of the step that is not the current one.
pub const LINK: egui::Color32 = egui::Color32::from_rgb(0x4D, 0xA3, 0xF0);
/// The step that is already behind the user.
pub const GREEN: egui::Color32 = egui::Color32::from_rgb(0x5F, 0xD3, 0x7E);
pub const GREEN_BG: egui::Color32 = egui::Color32::from_rgb(0x1E, 0x4D, 0x2B);
/// The action that stops the run.
pub const DANGER: egui::Color32 = egui::Color32::from_rgb(0xFF, 0x4D, 0x4D);
pub const DANGER_HOVER: egui::Color32 = egui::Color32::from_rgb(0xFF, 0x6B, 0x6B);
/// The background of the chosen line of the list.
pub const SELECTED_ROW: egui::Color32 = egui::Color32::from_rgb(0x3A, 0x1F, 0x24);
/// The warning in the log.
pub const WARNING: egui::Color32 = egui::Color32::from_rgb(0xF0, 0xC8, 0x78);
/// The error in the log.
pub const ERROR: egui::Color32 = egui::Color32::from_rgb(0xF0, 0x78, 0x78);

/// The corner of a card.
pub const RADIUS_CARD: u8 = 10;
/// The corner of a button.
pub const RADIUS_BUTTON: u8 = 6;
/// The corner of a field.
pub const RADIUS_FIELD: u8 = 5;

/// The state of one step of the journey.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StepState {
    /// The step the user is on.
    Active,
    /// The step the user already finished.
    Done,
    /// The step that is still ahead.
    Pending,
}

/// Put the dark theme of the product on the context.
///
/// The function is called on every frame, so the result does not depend on
/// what the user did before: the interface always has the same cara.
pub fn apply(ctx: &egui::Context) {
    ctx.set_theme(egui::Theme::Dark);
    let mut style = (*ctx.style()).clone();

    style.visuals.panel_fill = BG;
    style.visuals.window_fill = SURFACE;
    style.visuals.window_corner_radius = egui::CornerRadius::same(RADIUS_CARD);
    style.visuals.window_stroke = egui::Stroke::new(1.0_f32, BORDER);
    style.visuals.faint_bg_color = BG;
    style.visuals.extreme_bg_color = SURFACE;
    style.visuals.code_bg_color = SURFACE_2;
    style.visuals.text_edit_bg_color = Some(SURFACE_2);
    style.visuals.weak_text_color = Some(TEXT_MUTED);
    style.visuals.hyperlink_color = LINK;
    style.visuals.warn_fg_color = WARNING;
    style.visuals.error_fg_color = ERROR;
    style.visuals.selection.bg_fill = ACCENT;
    style.visuals.selection.stroke = egui::Stroke::new(1.0_f32, TEXT);

    let widgets = &mut style.visuals.widgets;
    widgets.noninteractive.bg_fill = SURFACE;
    widgets.noninteractive.weak_bg_fill = SURFACE;
    widgets.noninteractive.fg_stroke = egui::Stroke::new(1.0_f32, TEXT);
    widgets.noninteractive.corner_radius = egui::CornerRadius::same(RADIUS_CARD);
    widgets.inactive.bg_fill = SURFACE_2;
    widgets.inactive.weak_bg_fill = SURFACE_2;
    widgets.inactive.fg_stroke = egui::Stroke::new(1.0_f32, BORDER_STRONG);
    widgets.inactive.corner_radius = egui::CornerRadius::same(RADIUS_BUTTON);
    widgets.hovered.bg_fill = SURFACE_3;
    widgets.hovered.weak_bg_fill = SURFACE_3;
    widgets.hovered.fg_stroke = egui::Stroke::new(1.0_f32, TEXT);
    widgets.hovered.corner_radius = egui::CornerRadius::same(RADIUS_BUTTON);
    widgets.active.bg_fill = SURFACE_3;
    widgets.active.weak_bg_fill = SURFACE_3;
    widgets.active.fg_stroke = egui::Stroke::new(1.0_f32, TEXT);
    widgets.active.corner_radius = egui::CornerRadius::same(RADIUS_BUTTON);
    widgets.open.bg_fill = SURFACE_3;
    widgets.open.weak_bg_fill = SURFACE_3;
    widgets.open.fg_stroke = egui::Stroke::new(1.0_f32, TEXT);
    widgets.open.corner_radius = egui::CornerRadius::same(RADIUS_BUTTON);

    // The text of the interface: the title stands out, the rest reads
    // quietly.
    style.text_styles.insert(
        egui::TextStyle::Heading,
        egui::FontId::new(19.0, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Body,
        egui::FontId::new(13.5, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Small,
        egui::FontId::new(12.0, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Button,
        egui::FontId::new(13.5, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Monospace,
        egui::FontId::new(12.5, egui::FontFamily::Monospace),
    );

    style.spacing.item_spacing = egui::vec2(10.0, 10.0);
    style.spacing.button_padding = egui::vec2(14.0, 8.0);
    style.spacing.indent = 20.0;
    style.spacing.scroll = egui::style::ScrollStyle {
        bar_width: 10.0,
        floating_allocated_width: 10.0,
        ..Default::default()
    };
    style.spacing.slider_width = 12.0;
    style.spacing.interact_size.y = 28.0;

    ctx.set_style(style);
}

/// Draw a card: a surface with a border and a rounded corner.
///
/// Everything that is a group of things goes inside de um cartao, para que
/// a tela tenha blocos e nao uma lista solta de controles.
///
/// O cartao ocupa a largura toda do painel: um cartao que se encolhe no
/// canto deixa um vazio grande do lado, e o olho le o vazio antes do texto.
pub fn card<R>(
    ui: &mut egui::Ui,
    inner: impl FnOnce(&mut egui::Ui) -> R,
) -> egui::InnerResponse<R> {
    egui::Frame::new()
        .fill(SURFACE)
        .stroke(egui::Stroke::new(1.0_f32, BORDER))
        .corner_radius(egui::CornerRadius::same(RADIUS_CARD))
        .inner_margin(egui::Margin::same(16))
        .outer_margin(egui::Margin::same(4))
        .show(ui, |ui| {
            // O cartao ocupa a largura e a altura do painel: um cartao
            // que se encolhe no canto deixa um vazio grande do lado, e o
            // olho le o vazio antes do texto.
            ui.set_min_width(ui.available_width());
            ui.set_min_height(ui.available_height());
            // O cartao e uma coluna: o conteudo herda a direcao do pai, e
            // sem esta correcao o titulo, a dica e o botao ficariam lado a
            // lado em vez de um em cima do outro.
            let response = ui.vertical(inner);
            response.inner
        })
}

/// The title of a step.
pub fn step_title(ui: &mut egui::Ui, text: &str) {
    ui.label(egui::RichText::new(text).size(16.0).strong().color(TEXT));
}

/// The sentence that explains the step.
pub fn hint(ui: &mut egui::Ui, text: &str) {
    ui.label(egui::RichText::new(text).color(TEXT_MUTED));
}

/// A quiet text, for the details.
pub fn quiet(ui: &mut egui::Ui, text: impl Into<String>) {
    ui.label(
        egui::RichText::new(text.into())
            .color(TEXT_MUTED)
            .size(12.0),
    );
}

/// The number of a step, in a circle.
///
/// The circle is the number: red for the step the user is on, green for the
/// one that is already behind, gray for the one that is still ahead.
pub fn step_badge(ui: &mut egui::Ui, number: &str, state: StepState) {
    let (background, foreground) = match state {
        StepState::Active => (ACCENT, egui::Color32::WHITE),
        StepState::Done => (GREEN_BG, GREEN),
        StepState::Pending => (SURFACE_3, TEXT_MUTED),
    };
    let side = 26.0;
    let (rect, _) = ui.allocate_exact_size(egui::vec2(side, side), egui::Sense::hover());
    ui.painter()
        .rect_filled(rect, egui::CornerRadius::same(13), background);
    ui.painter().text(
        rect.center(),
        egui::Align2::CENTER_CENTER,
        number,
        egui::FontId::new(12.5, egui::FontFamily::Proportional),
        foreground,
    );
}

/// The line that joins two steps.
pub fn step_line(ui: &mut egui::Ui) {
    let (rect, _) = ui.allocate_exact_size(egui::vec2(28.0, 1.0), egui::Sense::hover());
    ui.painter().rect_filled(rect, 0.0, BORDER);
}

/// Draw a button with the colors of the product.
///
/// The egui paints a button with the colors of the style; here each button
/// gets the color of its meaning: red for the main action, blue for the
/// second one, gray for the quiet ones.
pub fn button(ui: &mut egui::Ui, text: &str, kind: ButtonKind) -> bool {
    with_button_visuals(ui, kind, |ui| ui.button(text).clicked())
}

/// A button that can be switched off.
pub fn button_enabled(ui: &mut egui::Ui, text: &str, kind: ButtonKind, enabled: bool) -> bool {
    with_button_visuals(ui, kind, |ui| {
        ui.add_enabled(enabled, egui::Button::new(text)).clicked()
    })
}

/// Paint a button with the color of its meaning, and give the style back.
///
/// The egui paints a button with the colors of the style; here each button
/// gets the color of what it means: red for the main action, blue for the
/// second one, gray for the quiet ones.
fn with_button_visuals<R>(
    ui: &mut egui::Ui,
    kind: ButtonKind,
    add: impl FnOnce(&mut egui::Ui) -> R,
) -> R {
    let (idle, hover, pressed, foreground) = match kind {
        ButtonKind::Primary => (ACCENT, ACCENT_HOVER, ACCENT_ACTIVE, egui::Color32::WHITE),
        ButtonKind::Secondary => (
            BLUE,
            BLUE_HOVER,
            egui::Color32::from_rgb(0x00, 0x5E, 0xA8),
            egui::Color32::WHITE,
        ),
        ButtonKind::Danger => (DANGER, DANGER_HOVER, DANGER, egui::Color32::WHITE),
        ButtonKind::Quiet => (SURFACE_2, SURFACE_3, SURFACE_3, TEXT),
    };

    // The style of the widget is saved, because the color of one button
    // cannot leak into the next one.
    let saved = ui.visuals().widgets.clone();
    {
        let visuals = &mut ui.visuals_mut().widgets;
        visuals.inactive.bg_fill = idle;
        visuals.inactive.weak_bg_fill = idle;
        visuals.inactive.fg_stroke = egui::Stroke::new(1.0_f32, foreground);
        visuals.inactive.corner_radius = egui::CornerRadius::same(RADIUS_BUTTON);
        visuals.hovered.bg_fill = hover;
        visuals.hovered.weak_bg_fill = hover;
        visuals.hovered.fg_stroke = egui::Stroke::new(1.0_f32, foreground);
        visuals.hovered.corner_radius = egui::CornerRadius::same(RADIUS_BUTTON);
        visuals.active.bg_fill = pressed;
        visuals.active.weak_bg_fill = pressed;
        visuals.active.fg_stroke = egui::Stroke::new(1.0_f32, foreground);
        visuals.active.corner_radius = egui::CornerRadius::same(RADIUS_BUTTON);
    }
    let result = add(ui);
    ui.visuals_mut().widgets = saved;
    result
}

/// The meaning of a button.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ButtonKind {
    /// The action the user wants: red.
    Primary,
    /// The action that helps: blue.
    Secondary,
    /// The action that stops: red, and clear about it.
    Danger,
    /// The action that only goes back: gray.
    Quiet,
}

/// A field where the user types.
pub fn field(ui: &mut egui::Ui, text: &mut String, hint_text: &str, width: f32) -> egui::Response {
    ui.visuals_mut().text_edit_bg_color = Some(SURFACE_2);
    let response = ui.add(
        egui::TextEdit::singleline(text)
            .hint_text(hint_text)
            .desired_width(width)
            .frame(true),
    );
    ui.visuals_mut().text_edit_bg_color = None;
    response
}

/// A line that shows the state of the run.
pub fn progress_bar(ui: &mut egui::Ui, ratio: f32, text: &str, width: f32) {
    let height = 18.0;
    let (rect, _) = ui.allocate_exact_size(egui::vec2(width, height), egui::Sense::hover());
    let radius = egui::CornerRadius::same(9);
    ui.painter().rect_filled(rect, radius, BG);
    ui.painter().rect_stroke(
        rect,
        radius,
        egui::Stroke::new(1.0_f32, BORDER_STRONG),
        egui::StrokeKind::Inside,
    );
    let filled = rect.width() * ratio.clamp(0.0, 1.0);
    if filled > 0.0 {
        let mut chunk = rect;
        chunk.max.x = rect.min.x + filled;
        ui.painter()
            .rect_filled(chunk, radius, egui::Color32::from_rgb(0xE6, 0x00, 0x23));
    }
    ui.painter().text(
        rect.center(),
        egui::Align2::CENTER_CENTER,
        text,
        egui::FontId::new(12.0, egui::FontFamily::Proportional),
        TEXT,
    );
}
