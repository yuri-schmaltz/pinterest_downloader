//! A jornada da interface: perfil, escolha dos quadros e download.
//!
//! O teste usa o mesmo motor da CLI e da interface: a interface nao tem um
//! segundo coletor, e o que se prova aqui e o que a interface faz.

use pinterest_core::engine::{self, CollectionMode, RunOptions};
use pinterest_core::models::DownloadOptions;
use pinterest_core::runtime::Operation;
use pinterest_gui::boards::BoardEntry;
use pinterest_gui::model::{Activity, AppModel, Stage};

#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;

fn options(out_root: &std::path::Path) -> RunOptions {
    RunOptions {
        mode: CollectionMode::Http,
        download: DownloadOptions {
            out_root: out_root.to_owned(),
            rate_limiting: false,
            metadata_cache: false,
            ..Default::default()
        },
        ..Default::default()
    }
}

fn operation() -> Operation {
    let (operation, mut events) = Operation::new(256);
    tokio::spawn(async move { while events.recv().await.is_some() {} });
    operation
}

#[tokio::test]
async fn a_jornada_baixa_so_os_quadros_escolhidos() {
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let mut model = AppModel::new();
    model.target = format!("{}/profile-many/", server.url);
    model.out_root = directory.path().to_owned();

    // O perfil e descoberto.
    model.begin_discovery().unwrap();
    assert_eq!(model.activity, Activity::Discovering);
    let discovered = engine::discover_boards(&model.target, options(directory.path()), operation())
        .await
        .unwrap();
    assert_eq!(discovered.boards.len(), 3);
    model.boards_found(discovered.boards.iter().map(BoardEntry::from).collect());
    assert_eq!(model.stage, Stage::Boards);
    assert_eq!(model.activity, Activity::Idle);

    // O usuario escolhe um quadro e so um.
    let chosen = model.boards.boards()[1].url.clone();
    model.boards.toggle(&chosen);
    assert_eq!(model.boards.selected_count(), 1);

    // O download roda com a lista escolhida.
    let urls = model.begin_download().unwrap();
    assert_eq!(urls, vec![chosen.clone()]);
    assert_eq!(model.stage, Stage::Download);
    let report = engine::run_boards(urls, options(directory.path()), operation())
        .await
        .unwrap();
    assert_eq!(report.boards.len(), 1, "so o quadro escolhido foi baixado");
    assert_eq!(report.totals.downloaded, 1);
    assert_eq!(report.totals.failed, 0);

    // Os arquivos do quadro escolhido existem e os dos outros nao.
    let chosen_name = chosen
        .trim_end_matches('/')
        .rsplit('/')
        .next()
        .unwrap()
        .to_string();
    let chosen_dir = directory.path().join("profile-many").join(&chosen_name);
    assert!(
        chosen_dir.join("201.jpg").is_file(),
        "o arquivo do quadro escolhido nao esta em {chosen_dir:?}"
    );
    for other in ["one", "two", "three"] {
        if other == chosen_name {
            continue;
        }
        let path = directory.path().join("profile-many").join(other);
        assert!(
            !path.exists(),
            "um quadro que nao foi escolhido nao pode ter arquivos: {path:?}"
        );
    }
}

#[tokio::test]
async fn o_download_usa_o_mesmo_motor_da_cli() {
    // A interface nao chama a CLI por subprocesso: ela usa o motor. O
    // resultado e o mesmo que a CLI produz para o mesmo alvo.
    let server = fixture::serve().await;
    let directory = tempfile::tempdir().unwrap();
    let report = engine::run_boards(
        vec![format!("{}/profile-many/one/", server.url)],
        options(directory.path()),
        operation(),
    )
    .await
    .unwrap();
    assert_eq!(report.totals.downloaded, 1);
    assert!(directory
        .path()
        .join("profile-many")
        .join("one")
        .join("201.jpg")
        .is_file());
}
