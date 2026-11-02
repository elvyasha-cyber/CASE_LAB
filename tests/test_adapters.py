import pytest

from case_lab.adapters.base import AdapterNotConfigured, ProcessResult
from case_lab.adapters.inbox_mail import fetch_mail_inbox
from case_lab.adapters.notify_manager import notify_manager
from case_lab.config import get_settings
from case_lab.runtime import run_live_batch


def test_mail_slot_asks_for_credentials(monkeypatch):
    monkeypatch.setenv("CASE_INPUT", "mail")
    monkeypatch.delenv("MAIL_HOST", raising=False)
    monkeypatch.delenv("MAIL_USER", raising=False)
    monkeypatch.delenv("MAIL_PASSWORD", raising=False)
    settings = get_settings(reload_env=False)
    with pytest.raises(AdapterNotConfigured, match="MAIL_HOST"):
        fetch_mail_inbox(settings)


def test_file_notify_writes_notification(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_NOTIFY", "file")
    settings = get_settings(reload_env=False)
    result = ProcessResult(
        message_id="MSG-001",
        decision="escalate",
        action_id="ESC-1",
        status="escalate",
        summary="нужны уточнения",
        next_action="передать менеджеру",
        escalate=True,
        payload={"message_id": "MSG-001"},
    )
    path = notify_manager(settings, result, out_dir=tmp_path)
    assert path is not None
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "передать менеджеру" in text


def test_live_http_mode_points_to_serve(monkeypatch, root, tmp_path):
    monkeypatch.setenv("CASE_INPUT", "http")
    monkeypatch.setenv("CASE_LLM", "replay")
    with pytest.raises(AdapterNotConfigured, match="serve"):
        run_live_batch(root=root, out_dir=tmp_path)
