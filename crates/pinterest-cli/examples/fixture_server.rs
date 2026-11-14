//! A local server that answers like a small board.
//!
//! It exists to smoke test the built binary: the CLI has to be able to
//! download from it without Python, Node or any other tool in the loop.
//! The pages come from the same fixture the regression suites use, so the
//! smoke test exercises the same paths.

#[path = "../../../tests/fixtures/parity/server.rs"]
mod fixture;

#[tokio::main]
async fn main() {
    let server = fixture::serve().await;
    println!("{}", server.url);
    // The server runs until the process is stopped.
    loop {
        tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
    }
}
