//! The graphical interface of the Pinterest Board Downloader.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use eframe::egui;
use pinterest_gui::app::App;

const USAGE: &str = "\
Pinterest Board Downloader - interface grafica

Uso:
    pinterest-gui [opcoes]

Opcoes:
    -h, --help       Mostra esta ajuda e sai
    -V, --version    Mostra a versao e sai

A interface faz o mesmo que a linha de comando: escolhe um perfil, marca
os quadros e baixa as midias. O cache de metadados e o layout dos arquivos
sao os mesmos, entao as duas ferramentas enxergam o mesmo material.
";

fn main() -> eframe::Result<()> {
    match std::env::args().nth(1).as_deref() {
        Some("-h") | Some("--help") => {
            print!("{USAGE}");
            return Ok(());
        }
        Some("-V") | Some("--version") => {
            println!("pinterest-gui {}", env!("CARGO_PKG_VERSION"));
            return Ok(());
        }
        Some(other) => {
            eprintln!("Opcao desconhecida: {other}\n");
            eprint!("{USAGE}");
            std::process::exit(2);
        }
        None => {}
    }
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .init();
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1100.0, 760.0])
            .with_min_inner_size([720.0, 520.0])
            .with_title("Pinterest Board Downloader"),
        ..Default::default()
    };
    run(options)
}

/// Draw the interface, with the OpenGL when the machine has one.
///
/// A machine without OpenGL 2.0 (um Windows sem driver de video, por
/// exemplo) mostraria um erro e nada mais. A wgpu desenha com DirectX ou
/// com Vulkan, e a interface funciona do mesmo jeito.
fn run(options: eframe::NativeOptions) -> eframe::Result<()> {
    let glow = eframe::NativeOptions {
        renderer: eframe::Renderer::Glow,
        ..options.clone()
    };
    match eframe::run_native(
        "Pinterest Board Downloader",
        glow,
        Box::new(|_cc| Ok(Box::new(App::new()))),
    ) {
        Ok(()) => Ok(()),
        Err(error) => {
            eprintln!(
                "O OpenGL nao esta disponivel neste computador ({error}). \
                 A interface vai usar o renderizador da wgpu."
            );
            let wgpu = eframe::NativeOptions {
                renderer: eframe::Renderer::Wgpu,
                ..options
            };
            eframe::run_native(
                "Pinterest Board Downloader",
                wgpu,
                Box::new(|_cc| Ok(Box::new(App::new()))),
            )
        }
    }
}
