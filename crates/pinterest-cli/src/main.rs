use clap::{Parser, ValueEnum};
use pinterest_core::{
    collector::CollectionOptions,
    engine::{self, CollectionMode, RunOptions},
    runtime::Completeness,
    DownloadOptions, Operation, PinterestError, RunEvent,
};
use std::{path::PathBuf, time::Duration};
use tokio::io::AsyncWriteExt;

#[derive(Debug, Clone, Copy, Default, ValueEnum)]
enum Mode {
    #[default]
    Auto,
    Browser,
    Http,
}

#[derive(Parser, Debug)]
#[command(
    name = "pinterest-cli",
    version,
    about = "Baixa quadros do Pinterest com coleta Chromium ou snapshot HTTP"
)]
struct Cli {
    /// URL de quadro/perfil ou nome de usuário
    #[arg(value_name = "URL_OU_USUARIO", conflicts_with = "user")]
    target: Option<String>,
    #[arg(short, long)]
    user: Option<String>,
    /// Destino dos arquivos (layout usuario/quadro, o mesmo do Python)
    #[arg(short, long, visible_alias = "out", default_value = "pins")]
    output: PathBuf,
    #[arg(short, long, default_value_t = 16)]
    workers: usize,
    /// Quadros processados ao mesmo tempo; cada um abre o proprio browser
    #[arg(long, default_value_t = 1)]
    boards_workers: usize,
    /// Não usa o cache de metadados de pins (resolução sempre pela rede)
    ///
    /// Tem o mesmo significado do `--no-cache` do Python: as duas
    /// ferramentas usam a mesma opção. Use `--force` para baixar
    /// de novo as mídias que já estão no disco.
    #[arg(long)]
    no_cache: bool,
    /// Não usa o cache de metadados de pins (mesmo que --no-cache)
    #[arg(long)]
    no_metadata_cache: bool,
    /// Baixa de novo as mídias que já estão no disco
    #[arg(long)]
    force: bool,
    /// Diretório do cache de metadados (default: cache do sistema)
    #[arg(long)]
    cache_dir: Option<PathBuf>,
    /// Dias que o cache de metadados vale; zero nunca expira
    #[arg(long, default_value_t = 30)]
    cache_ttl_days: u64,
    /// Desativa o limitador de taxa
    #[arg(long, alias = "no-rate-limiting")]
    no_rate_limit: bool,
    /// Ativa o limitador de taxa (o mesmo que desligar --no-rate-limit)
    #[arg(long)]
    rate_limiting: bool,
    /// Ajusta o numero de tarefas em voo conforme a carga da maquina
    #[arg(long)]
    adaptive_workers: bool,
    #[arg(long)]
    max_pins: Option<usize>,
    /// Auto usa Chromium; HTTP explícito tem completude desconhecida
    #[arg(long, value_enum, default_value_t = Mode::Auto)]
    mode: Mode,
    #[arg(long)]
    browser_executable: Option<PathBuf>,
    #[arg(long)]
    headful: bool,
    /// Aguarda confirmação após login no browser visível
    #[arg(long)]
    manual_login: bool,
    /// Desativa sandbox explicitamente em ambientes isolados que o exigem
    #[arg(long)]
    no_sandbox: bool,
    #[arg(long, default_value_t = 1.2)]
    scroll_pause: f64,
    #[arg(long, default_value_t = 150)]
    collection_timeout: u64,
    /// Eventos JSONL em stdout; progresso humano vai para stderr
    #[arg(long)]
    json_log: bool,
    /// Arquivo JSONL com os mesmos eventos tipados
    #[arg(long, default_value = "download_log.json")]
    log_file: Option<PathBuf>,
}

#[tokio::main]
async fn main() -> std::process::ExitCode {
    let cli = Cli::parse();
    match execute(cli).await {
        Ok(code) => std::process::ExitCode::from(code),
        Err((code, message)) => {
            eprintln!("Erro: {message}");
            std::process::ExitCode::from(code)
        }
    }
}

async fn execute(cli: Cli) -> Result<u8, (u8, String)> {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .init();
    let target = cli
        .user
        .or(cli.target)
        .ok_or_else(|| (2, "Informe URL ou usuário; use --help".into()))?;
    if cli.workers == 0
        || cli.boards_workers == 0
        || cli.max_pins == Some(0)
        || !cli.scroll_pause.is_finite()
        || cli.scroll_pause <= 0.0
        || cli.scroll_pause > 3600.0
        || cli.collection_timeout == 0
    {
        return Err((
            2,
            "Workers, quadros em paralelo, limite, pausa e timeout devem ser positivos; pausa máxima: 3600s".into(),
        ));
    }
    if cli.rate_limiting && cli.no_rate_limit {
        return Err((2, "--rate-limiting e --no-rate-limit se contradizem".into()));
    }
    if matches!(cli.mode, Mode::Http) && (cli.manual_login || cli.headful) {
        return Err((
            2,
            "Login/browser visível exigem --mode browser ou auto".into(),
        ));
    }
    let mut collection = CollectionOptions::default();
    collection.browser.executable = cli.browser_executable;
    collection.browser.headless = !cli.headful;
    collection.browser.no_sandbox = cli.no_sandbox;
    collection.scroll_pause = Duration::from_secs_f64(cli.scroll_pause);
    collection.max_duration = Duration::from_secs(cli.collection_timeout);
    collection.manual_login = cli.manual_login;
    let options = RunOptions {
        download: DownloadOptions {
            out_root: cli.output,
            workers: cli.workers,
            boards_workers: cli.boards_workers,
            use_cache: !cli.force,
            rate_limiting: cli.rate_limiting || !cli.no_rate_limit,
            adaptive: cli.adaptive_workers,
            max_pins: cli.max_pins,
            cache_dir: cli.cache_dir,
            metadata_cache: !(cli.no_cache || cli.no_metadata_cache),
            cache_ttl: std::time::Duration::from_secs(cli.cache_ttl_days.saturating_mul(86_400)),
        },
        collection,
        mode: match cli.mode {
            Mode::Auto => CollectionMode::Auto,
            Mode::Browser => CollectionMode::Browser,
            Mode::Http => CollectionMode::Http,
        },
    };
    let (operation, mut events) = Operation::new(256);
    let presentation_operation = operation.clone();
    let log = if let Some(path) = cli.log_file {
        Some(
            tokio::fs::File::create(path)
                .await
                .map_err(|error| (1, error.to_string()))?,
        )
    } else {
        None
    };
    let json = cli.json_log;
    let presenter = tokio::spawn(async move {
        let mut log = log;
        let (login_sender, mut login_input) = tokio::sync::mpsc::channel(1);
        // Tokio stdin uses blocking reads that can delay runtime shutdown until Enter.
        // A detached OS thread permits Ctrl+C to finish while a login prompt is pending.
        let mut awaiting_login = false;
        loop {
            tokio::select! {
                line = login_input.recv(), if awaiting_login => {
                    if matches!(line, Some(true)) {
                        presentation_operation.resume_login();
                    } else {
                        presentation_operation.cancel();
                    }
                    awaiting_login = false;
                },
                event = events.recv() => {
                    let Some(event) = event else { break; };
                    let serialized = serde_json::to_string(&event).map_err(|error| error.to_string())?;
                    if json {
                        let mut stdout = tokio::io::stdout();
                        stdout.write_all(format!("{serialized}\n").as_bytes()).await.map_err(|error| { presentation_operation.cancel(); error.to_string() })?;
                    }
                    if let Some(file) = &mut log {
                        file.write_all(serialized.as_bytes()).await.map_err(|error| { presentation_operation.cancel(); error.to_string() })?;
                        file.write_all(b"\n").await.map_err(|error| { presentation_operation.cancel(); error.to_string() })?;
                    }
                    match &event.event {
                        RunEvent::LoginRequired { url } => {
                            eprintln!("Faça login no browser para {url}; pressione Enter para continuar (Ctrl+C cancela).");
                            awaiting_login = true;
                            let sender = login_sender.clone();
                            std::thread::spawn(move || {
                                let mut input = String::new();
                                let confirmed = std::io::stdin().read_line(&mut input).is_ok_and(|bytes| bytes > 0);
                                let _ = sender.blocking_send(confirmed);
                            });
                        },
                        RunEvent::BoardStarted { board_url } if !json => eprintln!("Quadro: {board_url}"),
                        RunEvent::DownloadProgress { current, total } if !json => eprintln!("Mídias: {current}/{total}"),
                        RunEvent::Warning { message } => eprintln!("Aviso: {message}"),
                        RunEvent::Failed { message, .. } => eprintln!("Falha: {message}"),
                        _ => {},
                    }
                    if matches!(event.event, RunEvent::Finished { .. } | RunEvent::Failed { .. } | RunEvent::Cancelled) { break; }
                }
            }
        }
        if let Some(file) = &mut log {
            file.flush().await.map_err(|error| error.to_string())?;
        }
        Ok::<_, String>(())
    });
    let cancel = operation.clone();
    let signal = tokio::spawn(async move {
        if tokio::signal::ctrl_c().await.is_ok() {
            cancel.cancel();
        }
    });
    let result = engine::run_target(&target, options, operation.clone()).await;
    signal.abort();
    presenter
        .await
        .map_err(|error| (1, error.to_string()))?
        .map_err(|message| (1, message))?;
    drop(operation);
    match result {
        Ok(report) => {
            if !json {
                eprintln!(
                    "Concluído: {} novos, {} reutilizados, {} falhas",
                    report.totals.downloaded, report.totals.reused, report.totals.failed
                );
            }
            if report.totals.failed > 0
                || report.discovery_completeness == Completeness::Unknown
                || report
                    .boards
                    .iter()
                    .any(|board| board.completeness == Completeness::Unknown)
            {
                Ok(6)
            } else {
                Ok(0)
            }
        }
        Err(error) => {
            let code = match error {
                PinterestError::Cancelled => 130,
                PinterestError::Browser(_) => 3,
                PinterestError::PrivateProfile(_) | PinterestError::AuthenticationRequired(_) => 4,
                PinterestError::InvalidUrl(_) => 2,
                PinterestError::Extraction(_) => 7,
                _ => 1,
            };
            Err((code, engine::public_error_message(&error)))
        }
    }
}
