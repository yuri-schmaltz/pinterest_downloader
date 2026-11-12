//! The graphical interface of the Pinterest Board Downloader.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use eframe::egui;
use pinterest_gui::app::App;

fn main() -> eframe::Result<()> {
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
    eframe::run_native(
        "Pinterest Board Downloader",
        options,
        Box::new(|_cc| Ok(Box::new(App::new()))),
    )
}
