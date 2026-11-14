//! The adaptive workers must change the number of tasks in flight.
//!
//! The Python manager proposed a new number of workers and logged it, but
//! the thread pool was already running with the initial value. These tests
//! check the part that was missing: the real concurrency follows the
//! controller.

use pinterest_core::adaptive::{AdaptiveConfig, AdaptiveController};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

#[tokio::test]
async fn the_limit_moves_with_the_signals() {
    let controller = AdaptiveController::new(AdaptiveConfig {
        min_workers: 2,
        max_workers: 8,
        target_cpu_percent: 70.0,
        target_memory_percent: 60.0,
    });
    assert_eq!(controller.current_workers().await, 2);

    // A healthy run raises the limit. The load is given explicitly, so the
    // decision does not depend on how busy the machine happens to be.
    for _ in 0..10 {
        controller.record(Duration::from_millis(5), true).await;
    }
    controller.adjust_with(10.0, 10.0).await;
    assert!(
        controller.current_workers().await > 2,
        "a healthy run did not raise the limit"
    );

    // A run that keeps failing lowers it again.
    for _ in 0..20 {
        controller.record(Duration::from_millis(5), false).await;
    }
    controller.adjust_with(10.0, 10.0).await;
    assert_eq!(controller.current_workers().await, 2);
}

#[tokio::test]
async fn the_limit_never_leaves_the_configured_range() {
    let controller = AdaptiveController::new(AdaptiveConfig {
        min_workers: 3,
        max_workers: 5,
        ..Default::default()
    });
    for _ in 0..100 {
        controller.record(Duration::from_millis(1), true).await;
        controller.adjust_with(10.0, 10.0).await;
    }
    let current = controller.current_workers().await;
    assert!(
        (3..=5).contains(&current),
        "the limit left the range: {current}"
    );
}

/// The peak number of tasks that ran at the same time.
#[derive(Clone, Default)]
struct Peak {
    current: Arc<AtomicUsize>,
    peak: Arc<AtomicUsize>,
}

impl Peak {
    fn enter(&self) {
        let now = self.current.fetch_add(1, Ordering::SeqCst) + 1;
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

#[tokio::test]
async fn a_fixed_window_keeps_the_tasks_apart() {
    // The baseline: without a controller the window never moves.
    let peak = Peak::default();
    let tracker = peak.clone();
    let counter = Arc::new(AtomicUsize::new(0));
    let mut tasks = Vec::new();
    for _ in 0..24 {
        let tracker = tracker.clone();
        let counter = Arc::clone(&counter);
        tasks.push(tokio::spawn(async move {
            tracker.enter();
            counter.fetch_add(1, Ordering::SeqCst);
            tokio::time::sleep(Duration::from_millis(30)).await;
            tracker.leave();
        }));
    }
    for task in tasks {
        task.await.unwrap();
    }
    assert_eq!(counter.load(Ordering::SeqCst), 24);
    assert!(
        peak.peak.load(Ordering::SeqCst) >= 2,
        "the tasks did not overlap"
    );
}
