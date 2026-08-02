"""Small non-executable notification template renderer."""

import html
import re
from collections.abc import Mapping

_TOKEN = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
_UNSAFE_SYNTAX = ("{%", "%}", "${", "{{{", "}}}")


class UnsafeTemplate(ValueError):
    """Raised when a template is not in the deliberately small language."""


def render_template(
    template: str,
    values: Mapping[str, str],
    allowed_variables: frozenset[str],
    *,
    html_content: bool,
) -> str:
    if any(marker in template for marker in _UNSAFE_SYNTAX):
        raise UnsafeTemplate("Executable or unescaped template syntax is forbidden.")
    referenced = set(_TOKEN.findall(template))
    if referenced - allowed_variables:
        raise UnsafeTemplate("Template references a variable outside the allowlist.")
    residual = _TOKEN.sub("", template)
    if "{{" in residual or "}}" in residual:
        raise UnsafeTemplate("Template contains malformed variable syntax.")

    def replacement(match: re.Match[str]) -> str:
        value = values.get(match.group(1), "")
        cleaned = value.replace("\r", " ").replace("\n", " ")
        return html.escape(cleaned, quote=True) if html_content else cleaned

    return _TOKEN.sub(replacement, template)
