"""S5: Exit codes and checkpoint control flow."""
import pytest
from gtm.control import ExitCode, CheckpointPending


def test_exit_code_values():
    """ExitCode enum has exactly the required values."""
    assert ExitCode.SUCCESS == 0
    assert ExitCode.CHECKPOINT == 5
    assert ExitCode.STANDARDS == 6
    assert ExitCode.ERROR == 1


def test_exit_code_is_int_enum():
    """ExitCode members are usable as integers."""
    assert int(ExitCode.SUCCESS) == 0
    assert isinstance(ExitCode.SUCCESS, int)
    assert ExitCode.SUCCESS + 1 == 1


def test_checkpoint_pending_stores_attributes():
    """CheckpointPending exception stores file, action, resume as attributes."""
    exc = CheckpointPending(
        file="fit.json",
        action="score prospects",
        resume="python -m gtm.run fit myrun fit.json"
    )
    assert exc.file == "fit.json"
    assert exc.action == "score prospects"
    assert exc.resume == "python -m gtm.run fit myrun fit.json"


def test_checkpoint_pending_is_exception():
    """CheckpointPending is an Exception subclass."""
    exc = CheckpointPending(file="test.json", action="test", resume="test cmd")
    assert isinstance(exc, Exception)


def test_checkpoint_pending_can_be_raised():
    """CheckpointPending can be raised and caught."""
    with pytest.raises(CheckpointPending) as exc_info:
        raise CheckpointPending(file="test.json", action="test", resume="cmd")

    exc = exc_info.value
    assert exc.file == "test.json"
    assert exc.action == "test"
    assert exc.resume == "cmd"
