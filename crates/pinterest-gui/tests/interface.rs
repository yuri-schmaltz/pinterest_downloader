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

/// The Enter key in the profile field starts the search.
///
/// The field does not lose the focus when the Enter is pressed, so a
/// search that waits for the focus to leave the field never happens and
/// the user gets no answer at all.
#[test]
fn o_enter_no_campo_do_perfil_comeca_a_busca() {
    let mut app = App::new();
    // O espaco em volta e o que prova que a busca comecou: comecar a
    // busca limpa o campo, e a limpeza so acontece quando a busca entra.
    app.model.target = " alice ".to_owned();

    let context = egui::Context::default();
    let screen = egui::Rect::from_min_size(egui::pos2(0.0, 0.0), egui::vec2(1100.0, 760.0));

    // The first frame only draws, so the field can be found.
    let _ = context.run(
        egui::RawInput {
            screen_rect: Some(screen),
            ..Default::default()
        },
        |ctx| {
            app.update_ui(ctx);
        },
    );
    let field = context
        .read_response(egui::Id::new("campo-perfil"))
        .expect("the profile field was not drawn");
    let center = field.rect.center();

    // The user clicks the field: the press is one frame and the release is
    // the next one, like a real click.
    let _ = context.run(
        egui::RawInput {
            screen_rect: Some(screen),
            focused: true,
            events: vec![
                egui::Event::PointerMoved(center),
                egui::Event::PointerButton {
                    pos: center,
                    button: egui::PointerButton::Primary,
                    pressed: true,
                    modifiers: egui::Modifiers::default(),
                },
            ],
            ..Default::default()
        },
        |ctx| {
            app.update_ui(ctx);
        },
    );

    // And then presses Enter.
    let _ = context.run(
        egui::RawInput {
            screen_rect: Some(screen),
            focused: true,
            events: vec![egui::Event::Key {
                key: egui::Key::Enter,
                physical_key: None,
                pressed: true,
                repeat: false,
                modifiers: egui::Modifiers::default(),
            }],
            ..Default::default()
        },
        |ctx| {
            app.update_ui(ctx);
        },
    );

    assert_eq!(
        app.model.target, "alice",
        "the Enter key did not start the search"
    );
}

/// A profile without boards does not leave the user in a dead screen.
///
/// The user has to know that the profile has no boards, and needs a way
/// out of the screen: without the two things, the interface looks broken.
#[test]
fn um_perfil_sem_quadros_explica_e_deixa_voltar() {
    let mut app = App::new();
    app.model.boards_found(Vec::new());
    let shown = draw(&mut app);
    assert!(
        shown
            .iter()
            .any(|label| label.contains("Nenhum quadro encontrado")),
        "{shown:?}"
    );
    assert!(
        shown.iter().any(|label| label.contains("Voltar")),
        "{shown:?}"
    );
}

/// The filter that hides everything says so, and offers the way out.
#[test]
fn o_filtro_que_esconde_tudo_diz_e_deixa_limpar() {
    let mut app = App::new();
    app.model
        .boards_found(vec![board("https://pinterest.com/a/arte/", "Arte")]);
    app.model.boards.set_filter("zzz");
    let shown = draw(&mut app);
    assert!(
        shown
            .iter()
            .any(|label| label.contains("O filtro escondeu os quadros")),
        "{shown:?}"
    );
    assert!(
        shown.iter().any(|label| label.contains("Limpar filtro")),
        "{shown:?}"
    );
}

/// A new search does not keep the filter of the old profile.
///
/// The filter belongs to the boards of a profile. When the user looks for
/// another one, the old filter would hide every board of the new profile,
/// and the user would think that the profile has no boards.
#[test]
fn uma_busca_nova_nao_herda_o_filtro_do_perfil_anterior() {
    let mut app = App::new();
    app.model
        .boards_found(vec![board("https://pinterest.com/a/arte/", "Arte")]);
    app.model.boards.set_filter("arte");
    app.model.target = "alice".to_owned();
    app.model.begin_discovery().unwrap();
    assert_eq!(
        app.model.boards.filter(),
        "",
        "the filter of the old profile survived the new search"
    );
}

/// The fields the user types in are visible.
///
/// A field without a background is a line of text on the card, and the user
/// does not know that he can click there. The test looks for the box of the
/// field in the drawing of the screen.
#[test]
fn os_campos_tem_fundo_e_borda() {
    let mut app = App::new();
    let context = egui::Context::default();
    let input = egui::RawInput {
        screen_rect: Some(egui::Rect::from_min_size(
            egui::pos2(0.0, 0.0),
            egui::vec2(1100.0, 760.0),
        )),
        ..Default::default()
    };
    let output = context.run(input, |ctx| {
        app.update_ui(ctx);
    });

    let field = context
        .read_response(egui::Id::new("campo-perfil"))
        .expect("the profile field was not drawn");

    let mut found = false;
    for clipped in &output.shapes {
        if let egui::Shape::Rect(rect) = &clipped.shape {
            // The box of the field is the one around the text of the field.
            if !is_the_box_of(&rect.rect, &field.rect) {
                continue;
            }
            let fill = rect.fill;
            assert_eq!(
                (fill.r(), fill.g(), fill.b()),
                (0x2A, 0x2F, 0x38),
                "the field is not painted with the color of a field: {fill:?}"
            );
            // A border clear demais do egui fica como uma linha prateada
            // no campo escuro, e o campo parece um desenho mal feito.
            let border = rect.stroke.color;
            assert_eq!(
                (border.r(), border.g(), border.b()),
                (0x3A, 0x41, 0x4D),
                "the border of the field is not the border of the product: {border:?}"
            );
            found = true;
        }
    }
    assert!(found, "the field of the profile was not painted: {field:?}");
}

/// The filter field of the boards screen is painted like the profile field.
#[test]
fn o_campo_do_filtro_tem_fundo() {
    let mut app = App::new();
    app.model
        .boards_found(vec![board("https://pinterest.com/a/arte/", "Arte")]);

    let context = egui::Context::default();
    let input = egui::RawInput {
        screen_rect: Some(egui::Rect::from_min_size(
            egui::pos2(0.0, 0.0),
            egui::vec2(1100.0, 760.0),
        )),
        ..Default::default()
    };
    let output = context.run(input, |ctx| {
        app.update_ui(ctx);
    });

    let field = context
        .read_response(egui::Id::new("campo-filtro"))
        .expect("the filter field was not drawn");

    let mut found = false;
    for clipped in &output.shapes {
        if let egui::Shape::Rect(rect) = &clipped.shape {
            if !is_the_box_of(&rect.rect, &field.rect) {
                continue;
            }
            let fill = rect.fill;
            assert_eq!(
                (fill.r(), fill.g(), fill.b()),
                (0x2A, 0x2F, 0x38),
                "the filter field is not painted with the color of a field: {fill:?}"
            );
            found = true;
        }
    }
    assert!(found, "the filter field was not painted: {field:?}");
}

/// The shape is the box of the field, and not something else.
fn is_the_box_of(shape: &egui::Rect, field: &egui::Rect) -> bool {
    (shape.min.y - field.min.y).abs() <= 4.0
        && (shape.max.y - field.max.y).abs() <= 4.0
        && shape.min.x >= field.min.x - 4.0
        && shape.max.x <= field.max.x + 4.0
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
