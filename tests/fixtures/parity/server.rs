//! Local HTTP fixture shared by browser, core, and CLI regression suites.
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
};

pub struct Server {
    pub url: String,
    /// Number of pin pages served. A metadata cache must keep this number
    /// from growing when the same pin is resolved again.
    #[allow(dead_code)]
    pub pin_hits: Arc<AtomicUsize>,
    task: JoinHandle<()>,
}
impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

pub async fn serve() -> Server {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let pin_hits = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&pin_hits);
    let task = tokio::spawn(async move {
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let counter = Arc::clone(&counter);
            tokio::spawn(async move {
                let mut bytes = [0; 8192];
                let count = socket.read(&mut bytes).await.unwrap();
                let request = String::from_utf8_lossy(&bytes[..count]);
                let path = request.split_whitespace().nth(1).unwrap_or("/");
                if path.starts_with("/pin/") {
                    counter.fetch_add(1, Ordering::SeqCst);
                }
                let mut status = "200 OK";
                let (mime, body) = if path.starts_with("/resource/") {
                    let id = if path.ends_with("page=2") {
                        "102"
                    } else {
                        "101"
                    };
                    (
                        "application/json",
                        format!(
                            r#"{{"resource_response":{{"data":[{{"id":"{id}","title":"Pin {id}","images":{{"orig":{{"url":"/media/{id}.jpg"}}}}}}]}}}}"#
                        ),
                    )
                } else if path == "/alice/" {
                    ("text/html", r#"<html><body><a href="/alice/art/"><img src="/public-media/101.jpg">Art</a><a href="/bob/other/">Other user</a><a href="/alice/_saved/">Navigation</a><div style="height:1800px"></div><script>window.addEventListener('scroll',()=>{ if(!document.getElementById('later')){const a=document.createElement('a');a.id='later';a.href='/alice/nature/';a.textContent='Nature';document.body.appendChild(a);}});</script></body></html>"#.to_owned())
                } else if path == "/dom/art/" {
                    ("text/html", r#"<html><main data-test-id='board-feed'><a href='/pin/103/'>DOM only</a><div data-test-id='board-feed-end'></div></main><script>document.cookie='fixture_cookie=ok; path=/';</script></html>"#.to_owned())
                } else if path == "/pin/103/" {
                    ("text/html", r#"<html><meta content='/media/103.jpg?signature=keep&amp;x=1' property='og:image'></html>"#.to_owned())
                } else if path == "/snapshot/art/" {
                    ("text/html", r#"<html><script id="__PWS_DATA__">{"pins":[{"id":"101","images":{"orig":{"url":"/public-media/101.jpg"}}}]}</script></html>"#.to_owned())
                } else if path == "/empty/art/" {
                    ("text/html", "<html><main data-test-id='board-feed'><div data-test-id='board-feed-end'></div></main></html>".to_owned())
                } else if path == "/login/" {
                    (
                        "text/html",
                        "<html><form data-test-id='login-form'></form></html>".to_owned(),
                    )
                } else if path == "/session/check" {
                    ("text/html", "<html>session check</html>".to_owned())
                } else if path.starts_with("/media/") || path.starts_with("/public-media/") {
                    if path.starts_with("/media/") && !request.contains("fixture_cookie=ok") {
                        status = "403 Forbidden";
                    }
                    ("image/jpeg", "fixture image".to_owned())
                } else {
                    ("text/html", include_str!("dynamic_board.html").to_owned())
                };
                let _ = socket.write_all(format!("HTTP/1.1 {status}\r\nContent-Type: {mime}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await;
            });
        }
    });
    Server {
        url,
        pin_hits,
        task,
    }
}
