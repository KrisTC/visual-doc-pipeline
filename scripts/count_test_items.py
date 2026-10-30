"""Count selected pytest items before starting workers for a focused run."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


class ItemCounter:
    count = 0

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.count = len(session.items)


def main(arguments: list[str]) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    counter = ItemCounter()
    result = pytest.main([*arguments, "--collect-only", "-n", "0"], plugins=[counter])
    if result == 0:
        print(counter.count)
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
