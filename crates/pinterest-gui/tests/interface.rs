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

/// Every step fits inside the window.
///
/// The window is 1100x760: the bar de cima tem 66 pixels, a de baixo 64.
/// O que nao cabe na parte do meio e cortado, e o usuario perde um botao
/// sem avisar.
#[test]
fn todas_as_telas_cabem_na_janela() {
    // The profile step.
    check_fits(App::new(), "perfil");

    // The boards step.
    let mut boards = App::new();
    boards.model.boards_found(
        (0..12)
            .map(|index| {
                board(
                    &format!("https://pinterest.com/a/quadro-{index}/"),
                    &format!("Quadro {index}"),
                )
            })
            .collect(),
    );
    check_fits(boards, "quadros");

    // The download step.
    let mut download = App::new();
    download
        .model
        .boards_found(vec![board("https://pinterest.com/a/arte/", "Arte")]);
    download
        .model
        .boards
        .toggle("https://pinterest.com/a/arte/");
    download.model.begin_download().unwrap();
    check_fits(download, "download");
}

/// Draw one screen and check that nothing goes past the footer.
fn check_fits(mut app: App, name: &str) {
    let input = egui::RawInput {
        screen_rect: Some(egui::Rect::from_min_size(
            egui::pos2(0.0, 0.0),
            egui::vec2(1100.0, 760.0),
        )),
        ..Default::default()
    };
    let context = egui::Context::default();
    let output = context.run(input, |ctx| {
        app.update_ui(ctx);
    });

    // The top of the footer: nothing of the screen may go past it. The
    // fundo das barras e do painel e largo demais e nao conta.
    let limit = 760.0 - 64.0;
    for clipped in &output.shapes {
        if let egui::Shape::Rect(rect) = &clipped.shape {
            let rect = rect.rect;
            if rect.width() >= 1099.0 {
                continue;
            }
            assert!(
                !(rect.min.y < limit && rect.max.y > limit + 1.0),
                "the screen {name} goes past the footer: {rect:?}"
            );
        }
    }
}

/// The covers of the boards make a grid.
///
/// The shape of the drawing is checked here, because a cover that does not
/// fill the column leaves a hole in the middle of the row, and a hole is
/// something the eye sees before reading a single word.
#[test]
fn as_capas_dos_quadros_fazem_uma_grade() {
    let mut app = App::new();
    app.model.boards_found(
        (0..8)
            .map(|index| {
                board(
                    &format!("https://pinterest.com/a/quadro-{index}/"),
                    &format!("Quadro {index}"),
                )
            })
            .collect(),
    );

    // The drawing is made with the size of the real window, so the grid is
    // the one the user sees.
    let input = egui::RawInput {
        screen_rect: Some(egui::Rect::from_min_size(
            egui::pos2(0.0, 0.0),
            egui::vec2(1100.0, 760.0),
        )),
        ..Default::default()
    };
    let context = egui::Context::default();
    let output = context.run(input, |ctx| {
        app.update_ui(ctx);
    });

    // The covers are the squares the drawing painted. Each cover is painted
    // twice, once filled and once with a border, so the same square shows
    // up two times.
    let mut covers: Vec<egui::Rect> = output
        .shapes
        .iter()
        .filter_map(|clipped| match &clipped.shape {
            egui::Shape::Rect(rect) => Some(rect.rect),
            _ => None,
        })
        .filter(|rect| (rect.width() - rect.height()).abs() < 0.5 && rect.width() > 90.0)
        .collect();
    covers.sort_by_key(|rect| (rect.min.y.to_bits(), rect.min.x.to_bits()));
    covers.dedup_by_key(|rect| (rect.min.y.to_bits(), rect.min.x.to_bits()));
    assert_eq!(
        covers.len(),
        8,
        "the eight covers of the boards were not drawn: {covers:?}"
    );

    // All the covers have the same size.
    let side = covers[0].width();
    for cover in &covers {
        assert!(
            (cover.width() - side).abs() < 0.5 && (cover.height() - side).abs() < 0.5,
            "the covers do not have the same size: {covers:?}"
        );
    }

    // The covers stand in columns: the same horizontal place, one after
    // the other.
    let mut columns: Vec<f32> = covers.iter().map(|cover| cover.min.x).collect();
    columns.sort_by(|a, b| a.total_cmp(b));
    columns.dedup_by(|a, b| (*a - *b).abs() < 0.5);
    assert!(
        columns.len() >= 2,
        "the covers are all in one column: {covers:?}"
    );

    // And the columns do not overlap: the gap between two of them is the
    // gap of the grid, not a hole.
    for pair in columns.windows(2) {
        assert!(
            pair[1] - pair[0] >= side,
            "the columns of covers overlap: {covers:?}"
        );
    }

    // The rows line up too.
    let mut rows: Vec<f32> = covers.iter().map(|cover| cover.min.y).collect();
    rows.sort_by(|a, b| a.total_cmp(b));
    rows.dedup_by(|a, b| (*a - *b).abs() < 0.5);
    assert!(rows.len() >= 2, "the covers are all in one row: {covers:?}");
}
