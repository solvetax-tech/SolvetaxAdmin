"""Tests for EvolutionSink and the to_jid helper in backend/whatsapp/sinks.py.

All network-free — EvolutionSink is tested with a client double (monkeypatching
the module-level client functions).
"""
import pytest

from backend.whatsapp.sinks import EvolutionSink, to_jid


# ---------------------------------------------------------------------------
# to_jid helper
# ---------------------------------------------------------------------------

def test_to_jid_formats_10_digit_number():
    """10-digit number → 91{number}@s.whatsapp.net."""
    assert to_jid("9876543210") == "919876543210@s.whatsapp.net"


def test_to_jid_leading_zeros_preserved():
    """Leading zeros in the phone number must not be stripped."""
    assert to_jid("0000000001") == "910000000001@s.whatsapp.net"


# ---------------------------------------------------------------------------
# EvolutionSink delegation
# ---------------------------------------------------------------------------

async def test_evolution_sink_calls_client_send_text(monkeypatch):
    """EvolutionSink.send_text calls client.send_text with the correct JID."""
    import backend.whatsapp.client as client_mod

    calls = []

    async def fake_send_text(instance: str, jid: str, body: str) -> str:
        calls.append({"instance": instance, "jid": jid, "body": body})
        return "evo-msg-id-001"

    monkeypatch.setattr(client_mod, "send_text", fake_send_text)

    sink = EvolutionSink()
    result = await sink.send_text("9876543210", "Hello from test", "primary")

    assert result == "evo-msg-id-001"
    assert len(calls) == 1
    assert calls[0]["instance"] == "primary"
    assert calls[0]["jid"] == "919876543210@s.whatsapp.net"
    assert calls[0]["body"] == "Hello from test"


async def test_evolution_sink_propagates_evolution_error(monkeypatch):
    """EvolutionAPIError from the client propagates unchanged."""
    import backend.whatsapp.client as client_mod
    from backend.whatsapp.client import EvolutionAPIError

    async def fake_send_text(instance: str, jid: str, body: str) -> str:
        raise EvolutionAPIError("Evolution API returned 502: Bad Gateway")

    monkeypatch.setattr(client_mod, "send_text", fake_send_text)

    sink = EvolutionSink()
    with pytest.raises(EvolutionAPIError, match="502"):
        await sink.send_text("9876543210", "Hello", "primary")
