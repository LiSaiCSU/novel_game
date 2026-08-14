from __future__ import annotations

from apps.api import emailer
from engine.core.config import Settings


def test_implicit_tls_smtp_does_not_starttls(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: int) -> None:
            calls.append(("connect", (host, port, timeout)))

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def starttls(self) -> None:
            calls.append(("starttls", True))

        def login(self, username: str, password: str) -> None:
            calls.append(("login", (username, password)))

        def send_message(self, _message: object) -> None:
            calls.append(("send", True))

    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", FakeSMTP)
    settings = Settings(
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_username="sender@example.com",
        smtp_password="secret",
        smtp_from="sender@example.com",
        smtp_ssl=True,
        smtp_starttls=False,
    )

    emailer._send_sync(settings, "reader@example.com", "subject", "body")

    assert ("connect", ("smtp.example.com", 465, 15)) in calls
    assert ("login", ("sender@example.com", "secret")) in calls
    assert ("starttls", True) not in calls
    assert ("send", True) in calls
