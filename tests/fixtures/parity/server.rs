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
    /// Highest number of requests the server handled at the same time. A
    /// worker pool that really runs in parallel shows up here.
    #[allow(dead_code)]
    pub peak_concurrency: Arc<AtomicUsize>,
    task: JoinHandle<()>,
}

/// Tracks how many requests are in flight at the same time.
#[derive(Clone, Default)]
struct Concurrency {
    current: Arc<AtomicUsize>,
    peak: Arc<AtomicUsize>,
}

impl Concurrency {
    fn enter(&self) {
        let now = self.current.fetch_add(1, Ordering::SeqCst) + 1;
        // Keep the highest count seen.
        let mut peak = self.peak.load(Ordering::SeqCst);
        while now > peak {
            match self
                .peak
                .compare_exchange(peak, now, Ordering::SeqCst, Ordering::SeqCst)
            {
                Ok(_) => break,
                Err(observed) => peak = observed,
            }
        }
    }
    fn leave(&self) {
        self.current.fetch_sub(1, Ordering::SeqCst);
    }
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
    let concurrency = Concurrency::default();
    let peak_concurrency = Arc::clone(&concurrency.peak);
    let task = tokio::spawn(async move {
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let counter = Arc::clone(&counter);
            let concurrency = concurrency.clone();
            tokio::spawn(async move {
                concurrency.enter();
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
                    } else if path.contains("DupeResource") {
                        "901"
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
                } else if path == "/profile-many/" {
                    (
                        "text/html",
                        r#"<html><script id="__PWS_DATA__">{"boards":[{"url":"/profile-many/one/","name":"One"},{"url":"/profile-many/two/","name":"Two"},{"url":"/profile-many/three/","name":"Three"}]}</script></html>"#.to_owned(),
                    )
                } else if path.starts_with("/profile-many/") {
                    // A board that takes a moment, so a worker pool that really
                    // runs in parallel is visible in the concurrency counter.
                    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
                    (
                        "text/html",
                        r#"<html><script id="__PWS_DATA__">{"pins":[{"id":"201","images":{"orig":{"url":"/public-media/201.jpg"}}}]}</script></html>"#.to_owned(),
                    )
                } else if path == "/mixed/art/" {
                    // A board whose payload also carries the pins of another
                    // board. The page of a board asks for the feeds of other
                    // boards; those pins are not part of this board.
                    (
                        "text/html",
                        r#"<html><script id="__PWS_DATA__">{"pins":[
                            {"id":"801","images":{"orig":{"url":"/public-media/801.jpg"}},"board":{"url":"/mixed/art/","name":"Alvo"}},
                            {"id":"802","images":{"orig":{"url":"/public-media/802.jpg"}},"board":{"url":"/mixed/outro/","name":"Outro"}},
                            {"id":"803","images":{"orig":{"url":"/public-media/803.jpg"}}}
                        ]}</script></html>"#
                            .to_owned(),
                    )
                } else if path == "/dupes/art/" {
                    // The same pin arrives three ways: the DOM, the network
                    // payload and the DOM again after the scroll. The
                    // collector has to keep exactly one entry for it.
                    (
                        "text/html",
                        r#"<html><body><main data-test-id="board-feed">
                            <a href="/pin/901/">No DOM</a>
                        </main><script>
                            async function load() {
                                const response = await fetch('/resource/DupeResource/get/');
                                const payload = await response.json();
                                const main = document.querySelector('main');
                                for (const pin of payload.resource_response.data) {
                                    const a = document.createElement('a');
                                    a.href = '/pin/' + pin.id + '/';
                                    a.textContent = pin.title;
                                    main.appendChild(a);
                                }
                                const end = document.createElement('div');
                                end.dataset.testId = 'board-feed-end';
                                main.appendChild(end);
                            }
                            document.cookie = 'fixture_cookie=ok; path=/';
                            setTimeout(load, 100);
                            window.addEventListener('scroll', () => setTimeout(load, 100));
                        </script></body></html>"#
                            .to_owned(),
                    )
                } else if path == "/session-expired/art/" {
                    // A board whose session expires in the middle of the
                    // collection: the pins show up first and the login form
                    // arrives right after. The pins collected before the
                    // expiry have to be kept.
                    //
                    // The expiry happens once per browser session, and the
                    // marker in the session storage is what says so: after
                    // the user logs in the page opens normally, and the
                    // collection finishes instead of asking for a login
                    // forever. The scroll is not the trigger, because a
                    // window that is too tall never scrolls, and a scroll
                    // that never happens would leave the collection
                    // without the login it is supposed to ask for.
                    (
                        "text/html",
                        r#"<html><body><main data-test-id="board-feed">
                            <a href="/pin/1001/">Primeiro</a>
                            <a href="/pin/1002/">Segundo</a>
                        </main><div style="height:1800px"></div><script>
                            const expire = () => {
                                if (sessionStorage.getItem('session-expired')) return;
                                sessionStorage.setItem('session-expired', '1');
                                if (!document.querySelector('[data-test-id="login-form"]')) {
                                    const form = document.createElement('form');
                                    form.dataset.testId = 'login-form';
                                    document.body.appendChild(form);
                                }
                            };
                            setTimeout(expire, 250);
                        </script></body></html>"#
                            .to_owned(),
                    )
                } else if path == "/real/public/" {
                    // Uma captura real e sanitizada de um quadro publico. A
                    // pagina entrega os pins bloqueados para quem nao esta
                    // logado, o que e o que a captura prova.
                    (
                        "text/html",
                        include_str!("../real/quadro-publico.html").to_owned(),
                    )
                } else if path == "/neverend/art/" {
                    // A board whose feed never says that it ended and never
                    // stops changing. The collection has to stop on its own
                    // timeout and report that the result is partial.
                    (
                        "text/html",
                        r#"<html><body><main data-test-id="board-feed">
                            <a href="/pin/701/">Sem fim</a>
                            <img src="/public-media/701.jpg">
                            <div id="grow"></div>
                            <div style="height:3000px"></div>
                        </main><script>
                            window.addEventListener('scroll', () => {
                                const grow = document.getElementById('grow');
                                const item = document.createElement('div');
                                item.style.height = '40px';
                                item.textContent = 'mais';
                                grow.appendChild(item);
                            });
                        </script></body></html>"#
                            .to_owned(),
                    )
                } else if path == "/still/art/" {
                    // A board that stops changing without ever saying that
                    // it ended. The stability is not proof of completeness.
                    (
                        "text/html",
                        r#"<html><body><main data-test-id="board-feed">
                            <a href="/pin/702/">Parado</a>
                            <img src="/public-media/702.jpg">
                        </main></body></html>"#
                            .to_owned(),
                    )
                } else if path == "/origin/art/" {
                    // A board whose page also carries the pins that Pinterest
                    // recommends. Only the pins of the board belong to it.
                    (
                        "text/html",
                        r#"<html><body><main data-test-id="board-feed">
                            <a href="/pin/601/">Do quadro</a>
                        </main><section data-test-id="related-pins">
                            <a href="/pin/999/">Recomendado</a>
                        </section><script id="__PWS_DATA__">{"pins":[{"id":"602","images":{"orig":{"url":"/public-media/602.jpg"}}}],
                            "recommendations":[{"id":"998","images":{"orig":{"url":"/public-media/998.jpg"}}}]}</script></body></html>"#
                            .to_owned(),
                    )
                } else if path == "/expire/art/" {
                    // A board whose media URL expired: the media answers 403
                    // and the page of the pin knows the fresh URL.
                    (
                        "text/html",
                        r#"<html><script id="__PWS_DATA__">{"pins":[{"id":"501","images":{"orig":{"url":"/expired-media/501.jpg"}}}]}</script></html>"#.to_owned(),
                    )
                } else if path == "/pin/501/" {
                    (
                        "text/html",
                        r#"<html><meta content="/fresh-media/501.jpg" property="og:image"></html>"#
                            .to_owned(),
                    )
                } else if path == "/fresh-media/501.jpg" {
                    ("image/jpeg", "fresh image".to_owned())
                } else if path == "/expired-media/501.jpg" {
                    status = "403 Forbidden";
                    ("image/jpeg", "expired".to_owned())
                } else if path == "/slow/art/" {
                    // A board that never answers in time. The client has to
                    // give up on its own when the run is cancelled, without
                    // waiting for the network timeout.
                    tokio::time::sleep(std::time::Duration::from_secs(30)).await;
                    ("text/html", "<html>slow</html>".to_owned())
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
                // The page of the real capture asks for resources of other
                // hosts. The browser waits for them before saying that the
                // page is ready, and a machine without internet waits
                // forever. The policy says that only the fixture itself can
                // be used: the page loads at once and the test does not
                // depend on the network.
                let policy = "Content-Security-Policy: default-src 'self' \
                              'unsafe-inline' 'unsafe-eval' data: blob:;";
                let _ = socket.write_all(format!("HTTP/1.1 {status}\r\nContent-Type: {mime}\r\n{policy}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await;
                concurrency.leave();
            });
        }
    });
    Server {
        url,
        pin_hits,
        peak_concurrency,
        task,
    }
}
