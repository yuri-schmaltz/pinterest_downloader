use clap::Parser;
use indicatif::{ProgressBar, ProgressStyle};
use pinterest_core::{DownloadOptions, Downloader};
use std::collections::HashMap;
use std::path::PathBuf;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[derive(Parser, Debug)]
#[command(name = "pinterest-dl")]
#[command(version = "2.0.5")]
#[command(about = "High performance Pinterest Downloader em Rust puro", long_about = None)]
struct Cli {
    /// URL do quadro ou nome de usuário
    #[arg(value_name = "URL_OU_USUARIO")]
    target: Option<String>,

    /// Nome de usuário alternativo via flag
    #[arg(short, long)]
    user: Option<String>,

    /// Diretório de destino
    #[arg(short, long, default_value = "downloads")]
    output: PathBuf,

    /// Número de downloads simultâneos
    #[arg(short, long, default_value_t = 8)]
    workers: usize,

    /// Desativar cache local
    #[arg(long)]
    no_cache: bool,

    /// Desativar rate limiting
    #[arg(long)]
    no_rate_limit: bool,

    /// Limite máximo de pins para baixar
    #[arg(long)]
    max_pins: Option<usize>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new("info"))
        .with(tracing_subscriber::fmt::layer())
        .init();

    let cli = Cli::parse();
    let target = cli.user.or(cli.target);

    let Some(target_input) = target else {
        eprintln!("Erro: Forneça a URL do quadro ou usuário (use --help para ajuda)");
        std::process::exit(1);
    };

    println!("==================================================");
    println!("  Pinterest Downloader (Pure Rust v2.0.5)");
    println!("  Target: {}", target_input);
    println!("==================================================");

    let downloader = Downloader::new()?;
    let options = DownloadOptions {
        out_root: cli.output,
        workers: cli.workers,
        use_cache: !cli.no_cache,
        rate_limiting: !cli.no_rate_limit,
        max_pins: cli.max_pins,
    };

    println!("Inicializando download em {:?} com {} workers...", options.out_root, options.workers);

    // Exemplo de integração direta com o downloader em Rust
    let pin_map: HashMap<String, String> = HashMap::new();
    let result = downloader.download_board_images(&target_input, pin_map, &options).await?;

    println!("\nDownload finalizado com sucesso!");
    println!("Quadros/Imagens salvas em: {:?}", result.output_dir);

    Ok(())
}
