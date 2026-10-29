//! Rate limiter and backoff protection (equivalent to Python rate_limiter.py).

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

#[derive(Debug, Clone)]
pub struct RateLimiter {
    state: Arc<Mutex<RateLimiterState>>,
    consecutive_429: Arc<AtomicU64>,
}

#[derive(Debug)]
struct RateLimiterState {
    tokens: f64,
    max_tokens: f64,
    refill_rate_per_sec: f64,
    last_update: Instant,
    backoff_until: Option<Instant>,
}

impl RateLimiter {
    pub fn new(rate_per_sec: f64, burst_capacity: usize) -> Self {
        Self {
            state: Arc::new(Mutex::new(RateLimiterState {
                tokens: burst_capacity as f64,
                max_tokens: burst_capacity as f64,
                refill_rate_per_sec: rate_per_sec,
                last_update: Instant::now(),
                backoff_until: None,
            })),
            consecutive_429: Arc::new(AtomicU64::new(0)),
        }
    }

    pub async fn acquire(&self) {
        loop {
            let delay = {
                let mut state = self.state.lock().await;
                let now = Instant::now();

                // Checa backoff ativo
                if let Some(until) = state.backoff_until {
                    if now < until {
                        until - now
                    } else {
                        state.backoff_until = None;
                        Duration::ZERO
                    }
                } else {
                    // Token bucket
                    let elapsed = (now - state.last_update).as_secs_f64();
                    state.tokens = (state.tokens + elapsed * state.refill_rate_per_sec).min(state.max_tokens);
                    state.last_update = now;

                    if state.tokens >= 1.0 {
                        state.tokens -= 1.0;
                        return;
                    }

                    let needed = 1.0 - state.tokens;
                    Duration::from_secs_f64(needed / state.refill_rate_per_sec)
                }
            };

            if !delay.is_zero() {
                tokio::time::sleep(delay).await;
            }
        }
    }

    pub async fn record_429(&self, retry_after: Option<Duration>) {
        let count = self.consecutive_429.fetch_add(1, Ordering::SeqCst) + 1;
        let delay = retry_after.unwrap_or_else(|| {
            let base = 2.0_f64.powi((count as i32).min(5));
            Duration::from_secs_f64(base)
        });

        let mut state = self.state.lock().await;
        state.backoff_until = Some(Instant::now() + delay);
        state.tokens = 0.0;
    }

    pub fn record_success(&self) {
        self.consecutive_429.store(0, Ordering::SeqCst);
    }
}

impl Default for RateLimiter {
    fn default() -> Self {
        Self::new(10.0, 15)
    }
}
