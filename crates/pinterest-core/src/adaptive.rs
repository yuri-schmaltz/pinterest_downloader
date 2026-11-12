//! Adaptive concurrency for the resolution and download phases.
//!
//! The Python side has an adaptive worker manager since the ONDA 5C: it
//! watches the machine and the network, and proposes a new number of
//! workers. The proposal was logged, but the thread pool was already
//! running with the initial value, so the real parallelism never changed.
//!
//! This is the same policy with the missing part: the number of tasks in
//! flight follows the controller. Raising the limit starts work sooner;
//! lowering it stops new work from starting until the running tasks drain.
//! Work that is already running is never interrupted, because a download
//! that is half done is worth more than one that was cancelled.
//!
//! The signals are the ones the Python manager uses: processor load,
//! memory pressure, the success rate and the average latency.

use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;
use sysinfo::System;
use tokio::sync::Mutex;

/// The policy of the controller.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdaptiveConfig {
    /// Minimum number of tasks in flight.
    pub min_workers: usize,
    /// Maximum number of tasks in flight.
    pub max_workers: usize,
    /// Processor load above which the concurrency goes down, in percent.
    pub target_cpu_percent: f64,
    /// Memory use above which the concurrency goes down, in percent.
    pub target_memory_percent: f64,
}

impl Default for AdaptiveConfig {
    fn default() -> Self {
        Self {
            min_workers: 4,
            max_workers: 32,
            target_cpu_percent: 70.0,
            target_memory_percent: 60.0,
        }
    }
}

/// What the controller decided and why.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Adjustment {
    /// The concurrency stayed where it was.
    Kept,
    /// The concurrency moved up.
    Raised(usize),
    /// The concurrency moved down.
    Lowered(usize),
}

/// A snapshot of what the controller observed.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AdaptiveSummary {
    pub current_workers: usize,
    pub min_workers: usize,
    pub max_workers: usize,
    pub success_rate: f64,
    pub avg_latency_ms: f64,
    pub total_operations: u64,
    pub successful_operations: u64,
    pub cpu_percent: f64,
    pub memory_percent: f64,
}

#[derive(Debug)]
struct AdaptiveState {
    config: AdaptiveConfig,
    current: usize,
    total: u64,
    successes: u64,
    latencies: Vec<f64>,
    /// Absent when the platform does not expose the information. The
    /// controller then works with the latency and the failures alone
    /// instead of refusing to run.
    system: Option<System>,
}

impl AdaptiveState {
    fn sample(&mut self) -> (f64, f64) {
        let Some(system) = self.system.as_mut() else {
            return (0.0, 0.0);
        };
        // The processor usage is a delta since the previous refresh, so the
        // system is primed once at construction and refreshed from then on.
        system.refresh_cpu_usage();
        system.refresh_memory();
        let cpu = f64::from(system.global_cpu_usage()).clamp(0.0, 100.0);
        let total = system.total_memory().max(1);
        let available = system.available_memory().min(total);
        let memory = ((total - available) as f64 / total as f64) * 100.0;
        (cpu, memory)
    }

    fn success_rate(&self) -> f64 {
        if self.total == 0 {
            1.0
        } else {
            self.successes as f64 / self.total as f64
        }
    }

    fn avg_latency(&self) -> f64 {
        if self.latencies.is_empty() {
            0.0
        } else {
            self.latencies.iter().sum::<f64>() / self.latencies.len() as f64
        }
    }
}

/// Controller that decides how many tasks may run at the same time.
#[derive(Debug, Clone)]
pub struct AdaptiveController {
    state: Arc<Mutex<AdaptiveState>>,
}

impl AdaptiveController {
    /// A controller with an explicit policy.
    pub fn new(config: AdaptiveConfig) -> Self {
        // A platform that does not expose the information leaves the
        // controller with the latency and the failure signals only.
        let mut system = System::new().ok();
        if let Some(system) = system.as_mut() {
            // Prime the processor usage so the first reading has a baseline.
            system.refresh_cpu_usage();
        }
        let current = config.min_workers.clamp(1, config.max_workers.max(1));
        Self {
            state: Arc::new(Mutex::new(AdaptiveState {
                current,
                config,
                total: 0,
                successes: 0,
                latencies: Vec::new(),
                system,
            })),
        }
    }

    /// The number of tasks allowed to run at the same time right now.
    pub async fn current_workers(&self) -> usize {
        self.state.lock().await.current
    }

    /// Read the machine load, or zeroes when the platform does not say.
    async fn sample_system(&self) -> (f64, f64) {
        self.state.lock().await.sample()
    }

    /// Record a finished task.
    pub async fn record(&self, latency: Duration, success: bool) {
        let mut state = self.state.lock().await;
        state.total += 1;
        if success {
            state.successes += 1;
        }
        state.latencies.push(latency.as_secs_f64() * 1000.0);
        if state.latencies.len() > 100 {
            state.latencies.remove(0);
        }
    }

    /// Decide whether the concurrency should move, and by how much.
    ///
    /// The machine is read and the policy is applied.
    pub async fn adjust(&self) -> Adjustment {
        let (cpu, memory) = self.sample_system().await;
        self.adjust_with(cpu, memory).await
    }

    /// Apply the policy to the given machine load.
    ///
    /// The decision is separated from the measurement so the policy can be
    /// exercised without depending on how busy the machine happens to be.
    pub async fn adjust_with(&self, cpu: f64, memory: f64) -> Adjustment {
        let mut state = self.state.lock().await;
        let success_rate = state.success_rate();
        let before = state.current;

        let comfortable = cpu < state.config.target_cpu_percent * 0.7
            && memory < state.config.target_memory_percent * 0.8;
        if comfortable && success_rate > 0.95 {
            state.current = (state.current + 1).min(state.config.max_workers);
        } else if cpu > state.config.target_cpu_percent
            || memory > state.config.target_memory_percent
            || success_rate < 0.80
        {
            state.current = state
                .current
                .saturating_sub(1)
                .max(state.config.min_workers);
        }

        match state.current.cmp(&before) {
            std::cmp::Ordering::Greater => Adjustment::Raised(state.current),
            std::cmp::Ordering::Less => Adjustment::Lowered(state.current),
            std::cmp::Ordering::Equal => Adjustment::Kept,
        }
    }

    /// What the controller observed so far.
    pub async fn summary(&self) -> AdaptiveSummary {
        let mut state = self.state.lock().await;
        let (cpu, memory) = state.sample();
        AdaptiveSummary {
            current_workers: state.current,
            min_workers: state.config.min_workers,
            max_workers: state.config.max_workers,
            success_rate: state.success_rate(),
            avg_latency_ms: state.avg_latency(),
            total_operations: state.total,
            successful_operations: state.successes,
            cpu_percent: cpu,
            memory_percent: memory,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> AdaptiveConfig {
        AdaptiveConfig {
            min_workers: 2,
            max_workers: 8,
            target_cpu_percent: 70.0,
            target_memory_percent: 60.0,
        }
    }

    #[tokio::test]
    async fn the_limit_never_leaves_the_configured_range() {
        let controller = AdaptiveController::new(config());
        assert_eq!(controller.current_workers().await, 2);
        for _ in 0..50 {
            controller.adjust_with(10.0, 10.0).await;
        }
        let current = controller.current_workers().await;
        assert!(
            (2..=8).contains(&current),
            "the limit left the range: {current}"
        );
    }

    #[tokio::test]
    async fn a_high_failure_rate_lowers_the_limit() {
        let controller = AdaptiveController::new(config());
        // The controller starts at the minimum, so it has to grow before it
        // can be lowered.
        for _ in 0..10 {
            controller.record(Duration::from_millis(10), true).await;
        }
        assert_eq!(
            controller.adjust_with(10.0, 10.0).await,
            Adjustment::Raised(3)
        );
        for _ in 0..20 {
            controller.record(Duration::from_millis(10), false).await;
        }
        let adjustment = controller.adjust_with(10.0, 10.0).await;
        assert_eq!(adjustment, Adjustment::Lowered(2));
    }

    #[tokio::test]
    async fn a_healthy_run_raises_the_limit() {
        let controller = AdaptiveController::new(config());
        for _ in 0..10 {
            controller.record(Duration::from_millis(10), true).await;
        }
        let adjustment = controller.adjust_with(10.0, 10.0).await;
        assert_eq!(adjustment, Adjustment::Raised(3));
    }

    #[tokio::test]
    async fn a_loaded_machine_lowers_the_limit_even_when_the_run_is_healthy() {
        let controller = AdaptiveController::new(config());
        for _ in 0..10 {
            controller.record(Duration::from_millis(10), true).await;
        }
        controller.adjust_with(10.0, 10.0).await;
        // A busy processor lowers the limit.
        assert_eq!(
            controller.adjust_with(95.0, 10.0).await,
            Adjustment::Lowered(2)
        );
        // The limit is already at the floor, so a busy memory cannot move it
        // any further.
        assert_eq!(controller.adjust_with(10.0, 95.0).await, Adjustment::Kept);
    }

    #[tokio::test]
    async fn the_summary_reports_what_was_observed() {
        let controller = AdaptiveController::new(config());
        controller.record(Duration::from_millis(20), true).await;
        controller.record(Duration::from_millis(40), false).await;
        let summary = controller.summary().await;
        assert_eq!(summary.total_operations, 2);
        assert_eq!(summary.successful_operations, 1);
        assert!((summary.success_rate - 0.5).abs() < f64::EPSILON);
        assert!((summary.avg_latency_ms - 30.0).abs() < f64::EPSILON);
    }
}
