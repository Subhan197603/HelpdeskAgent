"""Safe notification rendering tests."""

import pytest

from apps.api.app.notifications.rendering import UnsafeTemplate, render_template

ALLOWED = frozenset({"ticket_key", "recipient_name"})


def test_html_values_are_escaped_and_headers_are_flattened() -> None:
    assert (
        render_template(
            "Hello {{ recipient_name }}: {{ticket_key}}",
            {"recipient_name": '<script>alert("x")</script>', "ticket_key": "IT-1\r\nBcc: bad"},
            ALLOWED,
            html_content=True,
        )
        == "Hello &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;: IT-1  Bcc: bad"
    )


@pytest.mark.parametrize(
    "template",
    [
        "{{ unknown }}",
        "{% include 'secret' %}",
        "${ticket_key}",
        "{{ ticket_key",
        "{{{ ticket_key }}}",
    ],
)
def test_unknown_malformed_and_executable_syntax_fails_closed(template: str) -> None:
    with pytest.raises(UnsafeTemplate):
        render_template(template, {"ticket_key": "IT-1"}, ALLOWED, html_content=False)
