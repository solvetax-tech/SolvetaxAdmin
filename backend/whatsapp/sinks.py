"""MessageSink protocol and built-in sinks.

The execution engine and send_service accept a sink rather than calling
Evolution API directly.  This makes the entire send path testable without
any HTTP mocking — pass DryRunSink in tests and simulations, EvolutionSink
(Phase 1) in production.

Only DryRunSink ships in Slice 0.  EvolutionSink is Phase 1.
"""
from typing import Protocol


class MessageSink(Protocol):
    """Minimal interface every sink must implement."""

    async def send_text(self, phone: str, body: str, instance: str) -> str:
        """Send *body* to *phone* via *instance*.

        Returns an opaque message ID string (e.g. the Evolution API key.id).
        """
        ...


class DryRunSink:
    """No-op sink that records sends in memory.

    Used by tests and the simulation endpoint (doc 09 §3.8).  No network
    calls, no DB writes — pure in-process recording.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, phone: str, body: str, instance: str) -> str:
        self.sent.append({"phone": phone, "body": body, "instance": instance})
        return "dry-run-fake-id"
