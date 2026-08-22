"""Tests for notification filtering, rendering and dispatch."""

from __future__ import annotations

import pytest

from agent import notifier, render
from agent.config import NotifierSettings
from agent.models import ChangeEvent
from tests.conftest import make_opportunity


def settings(**overrides) -> NotifierSettings:
    defaults = dict(
        resend_api_key=None,
        email_from=None,
        email_to=(),
        smtp_host=None,
        smtp_port=587,
        smtp_user=None,
        smtp_password=None,
        smtp_starttls=True,
        telegram_bot_token=None,
        telegram_chat_id=None,
        discord_webhook_url=None,
        dry_run=False,
    )
    defaults.update(overrides)
    return NotifierSettings(**defaults)


def event(kind="status_change", **overrides) -> ChangeEvent:
    opportunity = overrides.pop("opportunity", None) or make_opportunity(
        title="EO Training Course", status="Open", score=88
    )
    return ChangeEvent(
        kind=kind,
        opportunity=opportunity,
        previous_status=overrides.pop("previous_status", "Pending"),
        detail=overrides.pop("detail", ""),
    )


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class FakeHTTPClient:
    """Records posts instead of performing them."""

    def __init__(self, response=None, raises=None):
        self.posts: list[tuple[str, dict]] = []
        self._response = response or FakeResponse()
        self._raises = raises

    def post(self, url, json=None, headers=None):
        if self._raises:
            raise self._raises
        self.posts.append((url, json or {}))
        return self._response

    def close(self):
        pass


class TestShouldNotify:
    def test_only_notifiable_kinds_are_selected(self):
        events = (
            event("status_change"),
            event("new_high_match"),
            event("new_opportunity"),
            event("deadline_soon"),
        )
        selected = notifier.should_notify(events, first_run=False)
        assert [e.kind for e in selected] == ["status_change", "new_high_match"]

    def test_first_run_suppresses_everything(self):
        """Setting up must not produce an alert storm."""
        assert notifier.should_notify((event("status_change"),), first_run=True) == ()

    def test_no_events_yields_nothing(self):
        assert notifier.should_notify((), first_run=False) == ()


class TestRendering:
    def test_subject_names_a_single_newly_open_opportunity(self):
        assert "EO Training Course is now OPEN" in render.subject((event(),))

    def test_subject_counts_multiple_openings(self):
        subject = render.subject((event(), event()))
        assert "2 opportunities now OPEN" in subject

    def test_subject_reports_a_new_strong_match(self):
        subject = render.subject((event("new_high_match"),))
        assert "88% match" in subject

    def test_subject_with_no_events(self):
        assert render.subject(()) == "ESA Scout — no changes"

    def test_text_body_includes_status_transition_and_link(self):
        body = render.text_body((event(),))
        assert "was Pending" in body
        assert "https://example.esa.int/opportunity" in body

    def test_html_body_escapes_untrusted_titles(self):
        """Opportunity titles come from scraped HTML and must not inject markup."""
        hostile = make_opportunity(title="<script>alert(1)</script>", score=90)
        body = render.html_body((event(opportunity=hostile),))
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body

    def test_telegram_body_escapes_untrusted_titles(self):
        hostile = make_opportunity(title="<b>bold</b> & co", score=90)
        body = render.telegram_body((event(opportunity=hostile),))
        assert "&lt;b&gt;bold&lt;/b&gt; &amp; co" in body

    def test_dashboard_link_is_appended_when_configured(self):
        body = render.text_body((event(),), dashboard_url="https://scout.test")
        assert "https://scout.test" in body

    def test_telegram_body_respects_the_api_limit(self):
        events = tuple(
            event(opportunity=make_opportunity(id=f"i{n}", title="X" * 300, score=90))
            for n in range(40)
        )
        assert len(render.telegram_body(events)) <= render.TELEGRAM_LIMIT

    def test_discord_body_respects_the_api_limit(self):
        events = tuple(
            event(opportunity=make_opportunity(id=f"i{n}", title="X" * 300, score=90))
            for n in range(40)
        )
        assert len(render.discord_body(events)) <= render.DISCORD_LIMIT

    def test_overflow_is_summarised_rather_than_dropped_silently(self):
        events = tuple(
            event(opportunity=make_opportunity(id=f"i{n}", title=f"Item {n}", score=80))
            for n in range(20)
        )
        assert "and 8 more" in render.text_body(events)

    def test_empty_events_render_a_no_change_message(self):
        assert "No changes" in render.text_body(())
        assert "No changes" in render.html_body(())
        assert "no changes" in render.telegram_body(()).lower()
        assert "no changes" in render.discord_body(()).lower()


class TestChannels:
    def test_resend_is_used_when_an_api_key_is_present(self):
        client = FakeHTTPClient()
        config = settings(
            resend_api_key="re_test",
            email_from="scout@test",
            email_to=("me@test",),
        )
        result = notifier.send_email((event(),), config, client=client)
        assert result.sent
        url, payload = client.posts[0]
        assert url == notifier.RESEND_API_URL
        assert payload["to"] == ["me@test"]
        assert payload["html"] and payload["text"]

    def test_email_is_skipped_without_a_transport(self):
        result = notifier.send_email((event(),), settings(email_from="a@test"))
        assert not result.sent
        assert result.detail.startswith("skipped")

    def test_resend_http_error_is_reported_as_failure(self):
        client = FakeHTTPClient(FakeResponse(422, "invalid from address"))
        config = settings(
            resend_api_key="re_test", email_from="bad", email_to=("me@test",)
        )
        result = notifier.send_email((event(),), config, client=client)
        assert not result.sent
        assert "422" in result.detail

    def test_smtp_is_used_when_no_resend_key_is_present(self, monkeypatch):
        sent = {}

        class FakeSMTP:
            def __init__(self, host, port, timeout=None):
                sent["host"] = host
                sent["port"] = port

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def ehlo(self):
                sent.setdefault("ehlo", 0)
                sent["ehlo"] += 1

            def starttls(self):
                sent["starttls"] = True

            def login(self, user, password):
                sent["login"] = (user, password)

            def send_message(self, message):
                sent["message"] = message

        monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSMTP)
        config = settings(
            smtp_host="smtp.test",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
            email_from="scout@test",
            email_to=("me@test", "other@test"),
        )
        result = notifier.send_email((event(),), config)

        assert result.sent
        assert sent["host"] == "smtp.test" and sent["port"] == 587
        assert sent["starttls"] is True
        assert sent["login"] == ("user", "pass")
        message = sent["message"]
        assert message["To"] == "me@test, other@test"
        # Both a plain-text and an HTML alternative must be attached.
        assert message.get_body(("html",)) is not None
        assert message.get_body(("plain",)) is not None

    def test_smtp_failure_is_reported_not_raised(self, monkeypatch):
        class ExplodingSMTP:
            def __init__(self, *a, **k):
                raise OSError("smtp unreachable")

        monkeypatch.setattr(notifier.smtplib, "SMTP", ExplodingSMTP)
        config = settings(
            smtp_host="smtp.test", email_from="scout@test", email_to=("me@test",)
        )
        result = notifier.send_email((event(),), config)
        assert not result.sent
        assert "smtp unreachable" in result.detail

    def test_starttls_can_be_disabled(self, monkeypatch):
        sent = {}

        class FakeSMTP:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def ehlo(self):
                pass

            def starttls(self):
                sent["starttls"] = True

            def send_message(self, message):
                pass

        monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSMTP)
        config = settings(
            smtp_host="smtp.test",
            smtp_starttls=False,
            email_from="scout@test",
            email_to=("me@test",),
        )
        assert notifier.send_email((event(),), config).sent
        assert "starttls" not in sent

    def test_telegram_posts_to_the_bot_api(self):
        client = FakeHTTPClient()
        config = settings(telegram_bot_token="123:ABC", telegram_chat_id="42")
        result = notifier.send_telegram((event(),), config, client=client)
        assert result.sent
        url, payload = client.posts[0]
        assert "/bot123:ABC/sendMessage" in url
        assert payload["chat_id"] == "42"
        assert payload["parse_mode"] == "HTML"

    def test_telegram_is_skipped_without_a_chat_id(self):
        config = settings(telegram_bot_token="123:ABC")
        assert not notifier.send_telegram((event(),), config).sent

    def test_discord_posts_the_webhook_content(self):
        client = FakeHTTPClient()
        config = settings(discord_webhook_url="https://discord.test/hook")
        result = notifier.send_discord((event(),), config, client=client)
        assert result.sent
        url, payload = client.posts[0]
        assert url == "https://discord.test/hook"
        assert "ESA Scout" in payload["content"]

    def test_network_exception_becomes_a_failure_not_a_crash(self):
        client = FakeHTTPClient(raises=OSError("connection reset"))
        config = settings(discord_webhook_url="https://discord.test/hook")
        result = notifier.send_discord((event(),), config, client=client)
        assert not result.sent
        assert "connection reset" in result.detail


class TestDispatch:
    def test_all_configured_channels_receive_the_alert(self):
        client = FakeHTTPClient()
        config = settings(
            resend_api_key="re_test",
            email_from="scout@test",
            email_to=("me@test",),
            telegram_bot_token="123:ABC",
            telegram_chat_id="42",
            discord_webhook_url="https://discord.test/hook",
        )
        results = notifier.dispatch((event(),), config, client=client)
        assert all(r.sent for r in results)
        assert len(client.posts) == 3

    def test_one_broken_channel_does_not_block_the_others(self):
        class PartialClient(FakeHTTPClient):
            def post(self, url, json=None, headers=None):
                if "discord" in url:
                    raise OSError("discord down")
                return super().post(url, json, headers)

        client = PartialClient()
        config = settings(
            telegram_bot_token="123:ABC",
            telegram_chat_id="42",
            discord_webhook_url="https://discord.test/hook",
        )
        results = notifier.dispatch((event(),), config, client=client)
        by_channel = {r.channel: r for r in results}
        assert by_channel["telegram"].sent
        assert not by_channel["discord"].sent

    def test_no_events_sends_nothing(self):
        client = FakeHTTPClient()
        config = settings(discord_webhook_url="https://discord.test/hook")
        assert notifier.dispatch((), config, client=client) == ()
        assert client.posts == []

    def test_dry_run_renders_without_sending(self, capsys):
        client = FakeHTTPClient()
        config = settings(dry_run=True, discord_webhook_url="https://discord.test/hook")
        results = notifier.dispatch((event(),), config, client=client)
        assert client.posts == []
        assert results[0].channel == "dry-run"
        assert "EO Training Course" in capsys.readouterr().out

    def test_no_channel_configured_is_reported(self):
        results = notifier.dispatch((event(),), settings())
        assert results[0].detail == "skipped: no channel configured"
