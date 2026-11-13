//! Interface-independent operation lifecycle and bounded, typed events.

use crate::{PinterestError, Result};
use serde::{Deserialize, Serialize};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use tokio::sync::{mpsc, oneshot};
use tokio_util::sync::CancellationToken;

static NEXT_RUN: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CompletionReason {
    EndOfFeed,
    RequestedLimit,
    Stable,
    Timeout,
    Snapshot,
    Cancelled,
    /// The page hides the pins behind a login.
    ///
    /// The board is not empty: the visitor is not logged in. The reason
    /// says that the collection stopped because of the login and not
    /// because the feed ended.
    Gated,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Completeness {
    Complete,
    Limited,
    Unknown,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct RunTotals {
    pub discovered: usize,
    pub resolved: usize,
    pub downloaded: usize,
    pub reused: usize,
    pub verified: usize,
    pub failed: usize,
    pub skipped: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RunEvent {
    Started {
        target: String,
    },
    BoardsFound {
        count: usize,
    },
    BoardStarted {
        board_url: String,
    },
    CollectionProgress {
        count: usize,
    },
    CollectionFinished {
        count: usize,
        reason: CompletionReason,
        completeness: Completeness,
    },
    ResolutionProgress {
        resolved: usize,
        total: usize,
    },
    DownloadProgress {
        current: usize,
        total: usize,
    },
    LoginRequired {
        url: String,
    },
    Warning {
        message: String,
    },
    BoardFinished {
        totals: RunTotals,
    },
    Finished {
        totals: RunTotals,
    },
    Failed {
        code: String,
        message: String,
    },
    Cancelled,
}

impl RunEvent {
    fn is_progress(&self) -> bool {
        matches!(
            self,
            Self::CollectionProgress { .. }
                | Self::ResolutionProgress { .. }
                | Self::DownloadProgress { .. }
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RunEventEnvelope {
    pub schema_version: u8,
    pub run_id: String,
    pub sequence: u64,
    pub timestamp: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub board_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pin_id: Option<String>,
    pub event: RunEvent,
}

#[derive(Clone)]
pub struct Operation {
    pub run_id: String,
    cancel: CancellationToken,
    sender: mpsc::Sender<RunEventEnvelope>,
    sequence: Arc<AtomicU64>,
    login: Arc<std::sync::Mutex<Option<oneshot::Sender<()>>>>,
}

impl Operation {
    pub fn new(capacity: usize) -> (Self, mpsc::Receiver<RunEventEnvelope>) {
        let (sender, receiver) = mpsc::channel(capacity.max(1));
        (
            Self {
                run_id: format!(
                    "{}-{}-{}",
                    std::process::id(),
                    chrono::Utc::now().timestamp_millis(),
                    NEXT_RUN.fetch_add(1, Ordering::Relaxed)
                ),
                cancel: CancellationToken::new(),
                sender,
                sequence: Arc::new(AtomicU64::new(1)),
                login: Arc::new(std::sync::Mutex::new(None)),
            },
            receiver,
        )
    }

    pub fn cancel(&self) {
        self.cancel.cancel();
        self.login.lock().unwrap().take();
    }
    pub fn resume_login(&self) -> bool {
        self.login
            .lock()
            .unwrap()
            .take()
            .is_some_and(|sender| sender.send(()).is_ok())
    }
    pub async fn request_login(&self, url: &str) -> Result<()> {
        self.check_cancelled()?;
        let (sender, receiver) = oneshot::channel();
        {
            let mut pending = self.login.lock().unwrap();
            if pending.is_some() {
                return Err(PinterestError::Browser(
                    "Já existe um login pendente".into(),
                ));
            }
            *pending = Some(sender);
        }
        self.emit(
            RunEvent::LoginRequired {
                url: url.to_owned(),
            },
            Some(url),
            None,
        )
        .await;
        let result = tokio::select! {
            _ = self.cancel.cancelled() => Err(PinterestError::Cancelled),
            response = receiver => response.map_err(|_| PinterestError::Cancelled),
        };
        self.login.lock().unwrap().take();
        result
    }
    pub fn cancellation(&self) -> CancellationToken {
        self.cancel.clone()
    }
    pub fn check_cancelled(&self) -> Result<()> {
        if self.cancel.is_cancelled() {
            Err(PinterestError::Cancelled)
        } else {
            Ok(())
        }
    }

    /// Progress can be coalesced when the receiver falls behind. Control/terminal
    /// events wait for capacity; closing a receiver never stalls the operation.
    pub async fn emit(&self, event: RunEvent, board_url: Option<&str>, pin_id: Option<&str>) {
        let envelope = RunEventEnvelope {
            schema_version: 1,
            run_id: self.run_id.clone(),
            sequence: self.sequence.fetch_add(1, Ordering::Relaxed),
            timestamp: chrono::Utc::now().to_rfc3339(),
            board_url: board_url.map(str::to_owned),
            pin_id: pin_id.map(str::to_owned),
            event,
        };
        if envelope.event.is_progress() {
            let _ = self.sender.try_send(envelope);
        } else if matches!(
            envelope.event,
            RunEvent::Cancelled | RunEvent::Failed { .. } | RunEvent::Finished { .. }
        ) {
            // A terminal event must be drained by the presentation task, even
            // when cancellation has already fired. Sender closure is an error-free exit.
            let _ = self.sender.send(envelope).await;
        } else {
            tokio::select! {
                _ = self.cancel.cancelled() => {},
                _ = self.sender.send(envelope) => {},
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn progress_is_bounded_and_terminal_is_preserved() {
        let (operation, mut receiver) = Operation::new(1);
        operation
            .emit(RunEvent::CollectionProgress { count: 1 }, None, None)
            .await;
        operation
            .emit(RunEvent::CollectionProgress { count: 2 }, None, None)
            .await;
        let cloned = operation.clone();
        let terminal = tokio::spawn(async move {
            cloned
                .emit(
                    RunEvent::Finished {
                        totals: RunTotals::default(),
                    },
                    None,
                    None,
                )
                .await;
        });
        assert!(matches!(
            receiver.recv().await.unwrap().event,
            RunEvent::CollectionProgress { count: 1 }
        ));
        assert!(matches!(
            receiver.recv().await.unwrap().event,
            RunEvent::Finished { .. }
        ));
        terminal.await.unwrap();
    }

    #[tokio::test]
    async fn cancellation_interrupts_wait_for_a_full_control_queue() {
        let (operation, _receiver) = Operation::new(1);
        operation
            .emit(
                RunEvent::Started {
                    target: "alice".into(),
                },
                None,
                None,
            )
            .await;
        operation.cancel();
        tokio::time::timeout(
            std::time::Duration::from_millis(100),
            operation.emit(RunEvent::BoardsFound { count: 3 }, None, None),
        )
        .await
        .unwrap();
        assert!(matches!(
            operation.check_cancelled(),
            Err(PinterestError::Cancelled)
        ));
    }

    #[tokio::test]
    async fn envelopes_are_serializable_and_operations_have_distinct_ids() {
        let (one, mut receiver) = Operation::new(4);
        let (two, _) = Operation::new(4);
        assert_ne!(one.run_id, two.run_id);
        one.emit(
            RunEvent::BoardStarted {
                board_url: "/alice/art/".into(),
            },
            Some("/alice/art/"),
            None,
        )
        .await;
        let value = serde_json::to_value(receiver.recv().await.unwrap()).unwrap();
        assert_eq!(value["schema_version"], 1);
        assert_eq!(value["event"]["type"], "board_started");
        assert_eq!(value["board_url"], "/alice/art/");
    }
    #[tokio::test]
    async fn login_wait_resumes_without_races_and_cancels_promptly() {
        let (operation, mut events) = Operation::new(4);
        let cloned = operation.clone();
        let request = tokio::spawn(async move {
            cloned
                .request_login("https://www.pinterest.com/alice/")
                .await
        });
        assert!(matches!(
            events.recv().await.unwrap().event,
            RunEvent::LoginRequired { .. }
        ));
        assert!(operation.resume_login());
        request.await.unwrap().unwrap();
        assert!(!operation.resume_login());
        let cloned = operation.clone();
        let request = tokio::spawn(async move {
            cloned
                .request_login("https://www.pinterest.com/alice/")
                .await
        });
        assert!(matches!(
            events.recv().await.unwrap().event,
            RunEvent::LoginRequired { .. }
        ));
        operation.cancel();
        assert!(matches!(
            request.await.unwrap(),
            Err(PinterestError::Cancelled)
        ));
    }
}
