//! A interface desenha sem tela.
//!
//! O egui sabe desenhar fora de uma janela, e e o que este teste usa: a
//! interface e desenhada de verdade, com os dados de uma descoberta, e o
//! teste confere o que aparece. Um erro de desenho aparece aqui e nao
//! depois, na mao do usuario.

use eframe::egui;
use pinterest_gui::app::App;
use pinterest_gui::boards::BoardEntry;
use pinterest_gui::model::{Activity, Stage};

fn board(url: &str, title: &str) -> BoardEntry {
    BoardEntry {
        url: url.to_owned(),
        title: title.to_owned(),
        thumbnail_url: String::new(),
        pin_count: Some(12),
    }
}

/// Draw one frame and return what the interface showed.
///
/// The egui draws without a window, so the interface is really drawn here.
fn draw(app: &mut App) -> Vec<String> {
    let context = egui::Context::default();
    let _ = context.run(egui::RawInput::default(), |ctx| {
        app.update_ui(ctx);
    });
    app.last_labels.clone()
}

#[test]
fn a_primeira_tela_pede_o_perfil() {
    let mut app = App::new();
    let shown = draw(&mut app);
    assert!(
        shown.iter().any(|label| label.contains("Perfil")),
        "the profile step is missing: {shown:?}"
    );
    assert!(shown.iter().any(|label| label.contains("Buscar")));
}

#[test]
fn a_tela_dos_quadros_mostra_o_titulo_e_a_escolha() {
    let mut app = App::new();
    app.model.boards_found(vec![
        board("https://pinterest.com/a/arte/", "Arte"),
        board("https://pinterest.com/a/fotografia/", "Fotografia"),
    ]);
    assert_eq!(app.model.stage, Stage::Boards);
    let shown = draw(&mut app);
    assert!(
        shown.iter().any(|label| label.contains("Arte")),
        "{shown:?}"
    );
    assert!(
        shown.iter().any(|label| label.contains("Fotografia")),
        "{shown:?}"
    );
    assert!(
        shown
            .iter()
            .any(|label| label.contains("Baixar escolhidos")),
        "{shown:?}"
    );
}

#[test]
fn a_tela_do_download_mostra_o_resumo() {
    let mut app = App::new();
    app.model
        .boards_found(vec![board("https://pinterest.com/a/arte/", "Arte")]);
    app.model.boards.toggle("https://pinterest.com/a/arte/");
    app.model.begin_download().unwrap();
    assert_eq!(app.model.activity, Activity::Downloading);
    let shown = draw(&mut app);
    assert!(
        shown.iter().any(|label| label.contains("Novos:")),
        "{shown:?}"
    );
    assert!(
        shown.iter().any(|label| label.contains("Falhas:")),
        "{shown:?}"
    );
    assert!(
        shown.iter().any(|label| label.contains("Cancelar")),
        "{shown:?}"
    );
}

#[test]
fn um_erro_aparece_no_lugar_certo() {
    let mut app = App::new();
    app.model.discovery_failed("o perfil nao existe");
    let shown = draw(&mut app);
    assert!(
        shown
            .iter()
            .any(|label| label.contains("o perfil nao existe")),
        "{shown:?}"
    );
}

#[test]
fn o_dialogo_de_login_aparece_quando_o_browser_pede() {
    let mut app = App::new();
    app.model
        .login_requested("https://www.pinterest.com/alice/");
    let shown = draw(&mut app);
    assert!(
        shown.iter().any(|label| label.contains("Continuar")),
        "the login dialog is missing: {shown:?}"
    );
}
