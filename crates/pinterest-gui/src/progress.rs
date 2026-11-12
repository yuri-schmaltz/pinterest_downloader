//! The progress of a run, as the interface shows it.
//!
//! The model keeps what the interface needs: how far each board went, how
//! far the whole run went, the totals and the last lines of the log. The
//! log has a limit, because a long run would otherwise fill the memory.

use pinterest_core::runtime::{RunEvent, RunTotals};
use std::collections::{BTreeMap, VecDeque};

/// How far one board went.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BoardProgress {
    pub done: bool,
    pub total: usize,
    pub downloaded: usize,
    pub reused: usize,
    pub failed: usize,
}

impl BoardProgress {
    /// The number of media files that the board already has.
    pub fn current(&self) -> usize {
        self.downloaded + self.reused + self.failed
    }
}

/// One line of the log.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LogLine {
    pub level: LogLevel,
    pub message: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogLevel {
    Info,
    Warning,
    Error,
}

/// The progress of the whole run.
#[derive(Debug, Clone, Default)]
pub struct ProgressModel {
    boards: BTreeMap<String, BoardProgress>,
    /// The board the events are about right now.
    current: Option<String>,
    totals: RunTotals,
    logs: VecDeque<LogLine>,
    log_capacity: usize,
    finished: bool,
    cancelled: bool,
}

impl ProgressModel {
    /// A model that keeps the last `log_capacity` lines.
    pub fn new(log_capacity: usize) -> Self {
        Self {
            log_capacity: log_capacity.max(1),
            ..Default::default()
        }
    }

    pub fn boards(&self) -> &BTreeMap<String, BoardProgress> {
        &self.boards
    }

    pub fn totals(&self) -> &RunTotals {
        &self.totals
    }

    pub fn logs(&self) -> &VecDeque<LogLine> {
        &self.logs
    }

    pub fn is_finished(&self) -> bool {
        self.finished
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled
    }

    /// How many files the run got, in total.
    pub fn current(&self) -> usize {
        self.boards.values().map(BoardProgress::current).sum()
    }

    /// How many files the run expects to get, in total.
    pub fn total(&self) -> usize {
        self.boards.values().map(|board| board.total).sum()
    }

    /// Feed one event of the engine into the model.
    pub fn apply(&mut self, event: &RunEvent) {
        match event {
            RunEvent::BoardStarted { board_url } => {
                self.boards.entry(board_url.clone()).or_default();
                self.current = Some(board_url.clone());
            }
            RunEvent::CollectionProgress { count } => {
                if let Some(board) = self.current_board_mut() {
                    board.total = board.total.max(*count);
                }
            }
            RunEvent::DownloadProgress { current, total } => {
                if let Some(board) = self.current_board_mut() {
                    board.total = *total;
                    let known = board.current();
                    if *current > known {
                        board.downloaded += current - known;
                    }
                }
            }
            RunEvent::BoardFinished { totals } => {
                if let Some(board) = self.current_board_mut() {
                    board.done = true;
                    board.downloaded = totals.downloaded;
                    board.reused = totals.reused;
                    board.failed = totals.failed;
                    board.total = board
                        .total
                        .max(totals.downloaded + totals.reused + totals.failed);
                }
            }
            RunEvent::Finished { totals } => {
                self.finished = true;
                self.totals = totals.clone();
            }
            RunEvent::Cancelled => {
                self.cancelled = true;
                self.finished = true;
            }
            RunEvent::Failed { message, .. } => {
                self.finished = true;
                self.push(LogLevel::Error, message.clone());
            }
            RunEvent::Warning { message } => self.push(LogLevel::Warning, message.clone()),
            _ => {}
        }
    }

    /// The board the events are about.
    fn current_board_mut(&mut self) -> Option<&mut BoardProgress> {
        let key = self.current.clone()?;
        self.boards.get_mut(&key)
    }

    /// Add a line to the log, dropping the oldest when the log is full.
    pub fn push(&mut self, level: LogLevel, message: impl Into<String>) {
        self.logs.push_back(LogLine {
            level,
            message: message.into(),
        });
        while self.logs.len() > self.log_capacity {
            self.logs.pop_front();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pinterest_core::runtime::Completeness;

    #[test]
    fn o_log_nao_cresce_para_cima_do_limite() {
        let mut model = ProgressModel::new(3);
        for index in 0..10 {
            model.push(LogLevel::Info, format!("linha {index}"));
        }
        assert_eq!(model.logs().len(), 3);
        assert_eq!(model.logs().front().unwrap().message, "linha 7");
    }

    #[test]
    fn o_progresso_de_um_quadro_e_acompanhado() {
        let mut model = ProgressModel::new(10);
        model.apply(&RunEvent::BoardStarted {
            board_url: "https://pinterest.com/a/arte/".into(),
        });
        model.apply(&RunEvent::DownloadProgress {
            current: 2,
            total: 5,
        });
        let board = model.boards().values().next().unwrap();
        assert_eq!(board.downloaded, 2);
        assert_eq!(board.total, 5);
        assert_eq!(model.current(), 2);
        assert_eq!(model.total(), 5);
    }

    #[test]
    fn o_resumo_final_traz_os_totais() {
        let mut model = ProgressModel::new(10);
        model.apply(&RunEvent::Finished {
            totals: RunTotals {
                discovered: 5,
                resolved: 5,
                downloaded: 3,
                reused: 1,
                verified: 4,
                failed: 1,
                skipped: 0,
            },
        });
        assert!(model.is_finished());
        assert_eq!(model.totals().downloaded, 3);
        assert_eq!(model.totals().reused, 1);
        assert_eq!(model.totals().failed, 1);
    }

    #[test]
    fn o_cancelamento_e_marcado() {
        let mut model = ProgressModel::new(10);
        model.apply(&RunEvent::Cancelled);
        assert!(model.is_cancelled());
        assert!(model.is_finished());
    }

    #[test]
    fn a_falha_vira_uma_linha_de_log() {
        let mut model = ProgressModel::new(10);
        model.apply(&RunEvent::Failed {
            code: "browser".into(),
            message: "o browser nao abriu".into(),
        });
        assert!(model.is_finished());
        assert_eq!(model.logs().back().unwrap().level, LogLevel::Error);
        assert!(model.logs().back().unwrap().message.contains("browser"));
        let _ = Completeness::Unknown;
    }
}
