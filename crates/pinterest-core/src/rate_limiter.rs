//! Rate limiting with sliding windows and exponential backoff.
//!
//! The policy mirrors the Python `rate_limiter.py`: three sliding windows
//! (one second, one minute, one hour) plus an exponential backoff that a
//! `429 Too Many Requests` activates. The strictest window decides when the
//! next request may go out.
//!
//! `Retry-After` is honoured in both forms the HTTP specification allows:
//! a number of seconds and an HTTP date. A date in the past means "retry
//! now", not "retry in the past".

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

/// How many requests are allowed in each sliding window.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitConfig {
    pub max_requests_per_second: f64,
    pub max_requests_per_minute: usize,
    pub max_requests_per_hour: usize,
    pub backoff_on_429: Duration,
    pub backoff_multiplier: f64,
    pub max_backoff: Duration,
}

impl Default for RateLimitConfig {
    fn default() -> Self {
        Self {
            max_requests_per_second: 5.0,
            max_requests_per_minute: 200,
            max_requests_per_hour: 10_000,
            backoff_on_429: Duration::from_secs(60),
            backoff_multiplier: 2.0,
            max_backoff: Duration::from_secs(300),
        }
    }
}

/// A snapshot of what the limiter has done.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RateLimitStats {
    pub total_requests: u64,
    pub total_429s: u64,
    pub total_wait_time_seconds: f64,
    pub requests_last_second: usize,
    pub requests_last_minute: usize,
    pub requests_last_hour: usize,
    pub in_backoff: bool,
    pub backoff_seconds: f64,
}

#[derive(Debug)]
struct RateLimiterState {
    config: RateLimitConfig,
    requests_1s: VecDeque<Instant>,
    requests_1m: VecDeque<Instant>,
    requests_1h: VecDeque<Instant>,
    backoff_until: Option<Instant>,
    current_backoff: Duration,
    total_requests: u64,
    total_429s: u64,
    total_wait_time: Duration,
}

impl RateLimiterState {
    fn clean(&mut self, now: Instant) {
        while self
            .requests_1s
            .front()
            .is_some_and(|stamp| now.duration_since(*stamp) > Duration::from_secs(1))
        {
            self.requests_1s.pop_front();
        }
        while self
            .requests_1m
            .front()
            .is_some_and(|stamp| now.duration_since(*stamp) > Duration::from_secs(60))
        {
            self.requests_1m.pop_front();
        }
        while self
            .requests_1h
            .front()
            .is_some_and(|stamp| now.duration_since(*stamp) > Duration::from_secs(3600))
        {
            self.requests_1h.pop_front();
        }
    }

    fn wait_time(&self, now: Instant) -> Duration {
        let mut wait = Duration::ZERO;
        if self.requests_1s.len() as f64 >= self.config.max_requests_per_second {
            if let Some(oldest) = self.requests_1s.front() {
                let remaining = Duration::from_secs(1).saturating_sub(now.duration_since(*oldest));
                wait = wait.max(remaining);
            }
        }
        if self.requests_1m.len() >= self.config.max_requests_per_minute {
            if let Some(oldest) = self.requests_1m.front() {
                let remaining = Duration::from_secs(60).saturating_sub(now.duration_since(*oldest));
                wait = wait.max(remaining);
            }
        }
        if self.requests_1h.len() >= self.config.max_requests_per_hour {
            if let Some(oldest) = self.requests_1h.front() {
                let remaining =
                    Duration::from_secs(3600).saturating_sub(now.duration_since(*oldest));
                wait = wait.max(remaining);
            }
        }
        if let Some(until) = self.backoff_until {
            if now < until {
                wait = wait.max(until.duration_since(now));
            }
        }
        wait
    }
}

/// Rate limiter with sliding windows and backoff protection.
///
/// The windows are counted **per host**. A host that answers 429 must not
/// freeze the tasks of another host: they are different servers, with
/// different budgets.
#[derive(Debug, Clone)]
pub struct RateLimiter {
    config: RateLimitConfig,
    hosts: Arc<Mutex<HashMap<String, Arc<Mutex<RateLimiterState>>>>>,
    consecutive_429: Arc<AtomicU64>,
    waits: Arc<AtomicU64>,
}

impl RateLimiter {
    /// A limiter with the default policy.
    pub fn new() -> Self {
        Self::with_config(RateLimitConfig::default())
    }

    /// A limiter with an explicit policy.
    pub fn with_config(config: RateLimitConfig) -> Self {
        Self {
            config,
            hosts: Arc::new(Mutex::new(HashMap::new())),
            consecutive_429: Arc::new(AtomicU64::new(0)),
            waits: Arc::new(AtomicU64::new(0)),
        }
    }

    /// The state of one host. Each host has its own windows and backoff.
    async fn state_of(&self, host: &str) -> Arc<Mutex<RateLimiterState>> {
        let mut hosts = self.hosts.lock().await;
        hosts
            .entry(host.to_owned())
            .or_insert_with(|| {
                Arc::new(Mutex::new(RateLimiterState {
                    config: self.config.clone(),
                    requests_1s: VecDeque::new(),
                    requests_1m: VecDeque::new(),
                    requests_1h: VecDeque::new(),
                    backoff_until: None,
                    current_backoff: Duration::ZERO,
                    total_requests: 0,
                    total_429s: 0,
                    total_wait_time: Duration::ZERO,
                }))
            })
            .clone()
    }

    /// Wait until the strictest window allows another request.
    pub async fn acquire(&self) {
        self.acquire_for("").await;
    }

    /// Wait until the strictest window of a host allows another request.
    pub async fn acquire_for(&self, host: &str) {
        self.acquire_cancellable_for(host, None).await;
    }

    /// Wait until the strictest window allows another request, but give up
    /// when the operation is cancelled.
    ///
    /// The wait for a slot can be as long as the longest window, so a
    /// cancelled run must not wait for it: the plan asks for the cancellation
    /// to be observed in at most two seconds.
    pub async fn acquire_cancellable(&self, cancel: Option<&CancellationToken>) -> bool {
        self.acquire_cancellable_for("", cancel).await
    }

    /// Wait until the strictest window of a host allows another request,
    /// but give up when the operation is cancelled.
    pub async fn acquire_cancellable_for(
        &self,
        host: &str,
        cancel: Option<&CancellationToken>,
    ) -> bool {
        let state = self.state_of(host).await;
        loop {
            let delay = {
                let mut state = state.lock().await;
                let now = Instant::now();
                state.clean(now);
                let wait = state.wait_time(now);
                if wait.is_zero() {
                    state.requests_1s.push_back(now);
                    state.requests_1m.push_back(now);
                    state.requests_1h.push_back(now);
                    state.total_requests += 1;
                    return true;
                }
                state.total_wait_time += wait;
                wait
            };
            self.waits.fetch_add(1, Ordering::SeqCst);
            match cancel {
                Some(cancel) => {
                    tokio::select! {
                        biased;
                        _ = cancel.cancelled() => return false,
                        _ = tokio::time::sleep(delay) => {}
                    }
                }
                None => tokio::time::sleep(delay).await,
            }
        }
    }

    /// How many times the limiter had to hold a caller back.
    ///
    /// Zero means every caller found a slot ready. This is the observable
    /// difference between a rate-limited run and a bypassed one, without
    /// depending on wall-clock timing.
    pub fn waits(&self) -> u64 {
        self.waits.load(Ordering::SeqCst)
    }

    /// Report a `429 Too Many Requests`.
    ///
    /// The backoff grows exponentially and is capped by the configuration.
    /// A `Retry-After` from the server wins when it asks for a longer pause
    /// than the computed backoff, and never shortens it.
    pub async fn record_429(&self, retry_after: Option<Duration>) {
        self.record_429_for("", retry_after).await;
    }

    /// Report a `429 Too Many Requests` from one host.
    ///
    /// The backoff of a host does not touch the other hosts: a server that
    /// says "slow down" only speaks for itself.
    pub async fn record_429_for(&self, host: &str, retry_after: Option<Duration>) {
        let count = self.consecutive_429.fetch_add(1, Ordering::SeqCst) + 1;
        let state = self.state_of(host).await;
        let mut state = state.lock().await;
        state.total_429s += 1;
        let exponent = (count.saturating_sub(1)).min(16) as i32;
        let scaled = state.config.backoff_on_429.as_secs_f64()
            * state.config.backoff_multiplier.powi(exponent);
        let computed = Duration::from_secs_f64(scaled.min(state.config.max_backoff.as_secs_f64()));
        state.current_backoff = computed
            .max(retry_after.unwrap_or(Duration::ZERO))
            .min(state.config.max_backoff);
        state.backoff_until = Some(Instant::now() + state.current_backoff);
        state.requests_1s.clear();
        state.requests_1m.clear();
        state.requests_1h.clear();
    }

    /// Report a successful request, easing the backoff.
    pub async fn record_success(&self) {
        self.record_success_for("").await;
    }

    /// Report a successful request to one host, easing its backoff.
    pub async fn record_success_for(&self, host: &str) {
        self.consecutive_429.store(0, Ordering::SeqCst);
        let state = self.state_of(host).await;
        let mut state = state.lock().await;
        if !state.current_backoff.is_zero() {
            let reduced = state.config.backoff_multiplier.max(1.0);
            state.current_backoff =
                Duration::from_secs_f64((state.current_backoff.as_secs_f64() / reduced).max(0.0));
        }
    }

    /// What the limiter has done so far.
    pub async fn stats(&self) -> RateLimitStats {
        self.stats_for("").await
    }

    /// What the limiter has done for one host.
    pub async fn stats_for(&self, host: &str) -> RateLimitStats {
        let state = self.state_of(host).await;
        let mut state = state.lock().await;
        let now = Instant::now();
        state.clean(now);
        RateLimitStats {
            total_requests: state.total_requests,
            total_429s: state.total_429s,
            total_wait_time_seconds: state.total_wait_time.as_secs_f64(),
            requests_last_second: state.requests_1s.len(),
            requests_last_minute: state.requests_1m.len(),
            requests_last_hour: state.requests_1h.len(),
            in_backoff: state.backoff_until.is_some_and(|until| now < until),
            backoff_seconds: state.current_backoff.as_secs_f64(),
        }
    }
}

impl Default for RateLimiter {
    fn default() -> Self {
        Self::new()
    }
}

/// Parse a `Retry-After` header value.
///
/// Both forms of the header are accepted: a number of seconds and an HTTP
/// date. A date in the past means the request may be retried right away.
pub fn parse_retry_after(value: &str, now: SystemTime) -> Option<Duration> {
    let value = value.trim();
    if let Ok(seconds) = value.parse::<u64>() {
        return Some(Duration::from_secs(seconds));
    }
    let target = httpdate::parse_http_date(value).ok()?;
    match target.duration_since(now) {
        Ok(delta) => Some(delta),
        // The date is in the past: retry immediately.
        Err(_) => Some(Duration::ZERO),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retry_after_accepts_seconds() {
        let now = SystemTime::UNIX_EPOCH;
        assert_eq!(
            parse_retry_after("120", now),
            Some(Duration::from_secs(120))
        );
        assert_eq!(parse_retry_after("  7 ", now), Some(Duration::from_secs(7)));
    }

    #[test]
    fn a_retry_after_date_in_the_past_means_retry_now() {
        let now = SystemTime::UNIX_EPOCH + Duration::from_secs(2_000_000_000);
        assert_eq!(
            parse_retry_after("Sun, 06 Nov 1994 08:49:37 GMT", now),
            Some(Duration::ZERO)
        );
    }

    #[test]
    fn a_retry_after_date_in_the_future_waits_for_it() {
        // The reference is 2033-05-18 03:33:20 GMT; the header asks for
        // 2034-01-01, a little over half a year later.
        let now = SystemTime::UNIX_EPOCH + Duration::from_secs(2_000_000_000);
        let delta = parse_retry_after("Sun, 01 Jan 2034 00:00:00 GMT", now).unwrap();
        assert!(
            delta > Duration::from_secs(200 * 24 * 3600),
            "the delta should cover the remaining months, got {delta:?}"
        );
        assert!(delta <= Duration::from_secs(365 * 24 * 3600));
    }

    #[test]
    fn a_date_with_the_wrong_weekday_is_rejected() {
        // 2034-01-01 is a Sunday; the parser refuses a mismatched weekday
        // instead of trusting it.
        let now = SystemTime::UNIX_EPOCH + Duration::from_secs(2_000_000_000);
        assert_eq!(
            parse_retry_after("Mon, 01 Jan 2034 00:00:00 GMT", now),
            None
        );
    }

    #[test]
    fn an_unreadable_retry_after_is_ignored() {
        let now = SystemTime::UNIX_EPOCH;
        assert_eq!(parse_retry_after("soon", now), None);
    }

    #[tokio::test]
    async fn the_second_window_stops_the_sixth_request() {
        let limiter = RateLimiter::with_config(RateLimitConfig {
            max_requests_per_second: 5.0,
            max_requests_per_minute: 200,
            max_requests_per_hour: 10_000,
            ..Default::default()
        });
        for _ in 0..5 {
            limiter.acquire().await;
        }
        assert_eq!(limiter.waits(), 0, "the first five fit in the window");
        limiter.acquire().await;
        assert_eq!(limiter.waits(), 1, "the sixth has to wait for the window");
    }

    #[tokio::test]
    async fn a_429_starts_a_backoff_that_a_success_eases() {
        let limiter = RateLimiter::with_config(RateLimitConfig {
            backoff_on_429: Duration::from_secs(10),
            backoff_multiplier: 2.0,
            max_backoff: Duration::from_secs(60),
            ..Default::default()
        });
        limiter.record_429(None).await;
        let stats = limiter.stats().await;
        assert_eq!(stats.total_429s, 1);
        assert!(stats.in_backoff);
        assert_eq!(stats.backoff_seconds, 10.0);

        limiter.record_429(None).await;
        assert_eq!(limiter.stats().await.backoff_seconds, 20.0);

        limiter.record_success().await;
        assert_eq!(limiter.stats().await.backoff_seconds, 10.0);
    }

    #[tokio::test]
    async fn retry_after_never_shortens_the_backoff_but_extends_it() {
        let limiter = RateLimiter::with_config(RateLimitConfig {
            backoff_on_429: Duration::from_secs(10),
            max_backoff: Duration::from_secs(60),
            ..Default::default()
        });
        limiter.record_429(Some(Duration::from_secs(30))).await;
        assert_eq!(limiter.stats().await.backoff_seconds, 30.0);

        let other = RateLimiter::with_config(RateLimitConfig {
            backoff_on_429: Duration::from_secs(60),
            max_backoff: Duration::from_secs(60),
            ..Default::default()
        });
        other.record_429(Some(Duration::from_secs(1))).await;
        assert_eq!(
            other.stats().await.backoff_seconds,
            60.0,
            "a one second Retry-After must not shorten the backoff"
        );
    }

    #[tokio::test]
    async fn um_429_de_um_host_nao_congela_o_outro() {
        // A server that says "slow down" speaks only for itself. The tasks
        // of another host have to keep going.
        let limiter = RateLimiter::with_config(RateLimitConfig {
            backoff_on_429: Duration::from_secs(60),
            max_backoff: Duration::from_secs(60),
            max_requests_per_second: 1.0,
            ..Default::default()
        });
        limiter.record_429_for("lento.example", None).await;
        assert!(limiter.stats_for("lento.example").await.in_backoff);

        // The other host has no backoff and its own window.
        let other = limiter.stats_for("rapido.example").await;
        assert!(!other.in_backoff);
        assert_eq!(other.total_429s, 0);

        let started = Instant::now();
        limiter.acquire_for("rapido.example").await;
        assert!(
            started.elapsed() < Duration::from_millis(200),
            "o host que respondeu bem esperou {:?}",
            started.elapsed()
        );
    }

    #[tokio::test]
    async fn cada_host_tem_a_sua_janela() {
        let limiter = RateLimiter::with_config(RateLimitConfig::default());
        limiter.acquire_for("a.example").await;
        limiter.acquire_for("b.example").await;
        // Each host counts its own requests: the request of one host does
        // not use the budget of another.
        assert_eq!(limiter.stats_for("a.example").await.total_requests, 1);
        assert_eq!(limiter.stats_for("b.example").await.total_requests, 1);
        assert_eq!(limiter.stats_for("c.example").await.total_requests, 0);
        assert_eq!(limiter.waits(), 0);
    }

    #[tokio::test]
    async fn a_cancelled_wait_does_not_wait_for_the_window() {
        // A saturated hour window would hold the caller for a long time.
        // A cancelled operation has to be released at once.
        let limiter = RateLimiter::with_config(RateLimitConfig {
            max_requests_per_second: 1.0,
            max_requests_per_minute: 1,
            max_requests_per_hour: 1,
            ..Default::default()
        });
        limiter.acquire().await;
        let cancel = CancellationToken::new();
        cancel.cancel();
        let started = Instant::now();
        assert!(!limiter.acquire_cancellable(Some(&cancel)).await);
        assert!(
            started.elapsed() < Duration::from_millis(200),
            "the cancelled wait took {:?}",
            started.elapsed()
        );
    }

    #[tokio::test]
    async fn the_backoff_is_capped() {
        let limiter = RateLimiter::with_config(RateLimitConfig {
            backoff_on_429: Duration::from_secs(30),
            backoff_multiplier: 4.0,
            max_backoff: Duration::from_secs(120),
            ..Default::default()
        });
        for _ in 0..10 {
            limiter.record_429(None).await;
        }
        assert_eq!(limiter.stats().await.backoff_seconds, 120.0);
    }
}
