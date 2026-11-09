"""Write the OpenAPI schema used to generate the web app's typed client."""

import json
import sys
from pathlib import Path

from blackmamba.main import create_app

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
out.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")
