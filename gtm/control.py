"""S5: Exit codes and checkpoint control flow."""
from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes for gtm.run pipeline stages."""
    SUCCESS = 0
    ERROR = 1
    CHECKPOINT = 5
    STANDARDS = 6


def writes_enabled(live: bool) -> bool:
    """Guard for any external-sink write (Sheet push, future GitHub/HubSpot, ...).

    Every sink call site checks this instead of re-inlining the condition, so
    Slice 6/7's new sinks share one gate.
    """
    return live


class CheckpointPending(Exception):
    """Raised when a stage reaches a checkpoint and needs user approval."""

    def __init__(self, file: str, action: str, resume: str):
        self.file = file
        self.action = action
        self.resume = resume
        super().__init__(f"Checkpoint: {action} ({file})")
