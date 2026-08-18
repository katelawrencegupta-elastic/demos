#!/usr/bin/env python3
"""Create or overwrite the Kibana data view for workshop platform logs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import DATA_VIEW_ID, DATA_VIEW_NAME, kibana_url  # noqa: E402
from create_kibana import upsert_data_view  # noqa: E402


def main() -> None:
    view = upsert_data_view()
    dv = view.get("data_view", view)
    print(f"data_view: {dv.get('name') or DATA_VIEW_NAME} id={dv.get('id') or DATA_VIEW_ID}")
    print(kibana_url(f"/app/discover#/?_a=(index:'{DATA_VIEW_ID}')"))


if __name__ == "__main__":
    main()
