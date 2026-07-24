"""MessageSink protocol and built-in sinks.

The execution engine and send_service accept a sink rather than calling
Evolution API directly.  This makes the entire send path testable without
any HTTP mocking — pass DryRunSink in tests and simulations, EvolutionSink
in production.

DryRunSink ships in Slice 0.  EvolutionSink ships in Phase 1 (this module).
"""
from typing import Protocol

from backend.whatsapp import client as evo_client


def to_jid(phone: str) -> str:
    """Convert a 10-digit Indian mobile number to a WhatsApp JID.

    Example: '9876543210' → '919876543210@s.whatsapp.net'
    """
    return f"91{phone}@s.whatsapp.net"


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


class EvolutionSink:
    """Production sink: formats the JID and delegates to the Evolution API client.

    Formats phone as 91{phone}@s.whatsapp.net and calls client.send_text.
    EvolutionAPIError propagates to the caller unchanged.
    """

    async def send_text(self, phone: str, body: str, instance: str) -> str:
        jid = to_jid(phone)
        return await evo_client.send_text(instance, jid, body)
