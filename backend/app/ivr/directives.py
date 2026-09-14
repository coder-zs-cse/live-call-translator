"""What the IVR decided, before it becomes XML.

The service layer returns these; the API layer turns them into Vobiz elements.
That split is what keeps the state machine unit-testable without parsing XML,
and keeps vendor syntax out of the business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GatherSpec:
    """Collect DTMF and/or speech, then POST to `action_path`."""

    action_path: str
    num_digits: int | None = None
    finish_on_key: str = "#"
    accept_speech: bool = False
    execution_timeout: int = 10
    hints: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IvrDirective:
    """One turn of the IVR.

    Exactly one of `gather`, `bridge` or `hangup` is normally set; `speak` can
    accompany any of them.
    """

    speak: list[str] = field(default_factory=list)
    gather: GatherSpec | None = None
    #: Hand the leg to the media pipeline - the terminal state.
    bridge: bool = False
    hangup: bool = False

    @staticmethod
    def say_and_hangup(lines: list[str]) -> IvrDirective:
        return IvrDirective(speak=lines, hangup=True)
