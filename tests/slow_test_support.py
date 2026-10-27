"""Marker for tests that the runners skip when invoked with --fast."""

from __future__ import annotations

import os
import unittest
from collections.abc import Callable

from scripts.run_tests import FAST_TESTS_ENVIRONMENT_VARIABLE


def slow_test[TestCaseT: unittest.TestCase](
    test: Callable[[TestCaseT], None],
) -> Callable[[TestCaseT], None]:
    """Skip a slow test, with a visible reason, only when the runner was given --fast."""
    return unittest.skipIf(
        os.environ.get(FAST_TESTS_ENVIRONMENT_VARIABLE) == "1",
        "Slow test skipped by --fast; run without --fast for the complete suite.",
    )(test)
