"""Write the current OpenAPI contract to the documentation tree."""

import json
from pathlib import Path

from apps.api.app.main import create_app


def main() -> None:
    destination = Path("docs/api/openapi.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
