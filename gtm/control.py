"""S5: Exit codes and checkpoint control flow."""
from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes for gtm.run pipeline stages."""
    SUCCESS = 0
    ERROR = 1
    CHECKPOINT = 5
    STANDARDS = 6


class CheckpointPending(Exception):
    """Raised when a stage reaches a checkpoint and needs user approval."""

    def __init__(self, file: str, action: str, resume: str):
        self.file = file
        self.action = action
        self.resume = resume
        super().__init__(f"Checkpoint: {action} ({file})")
