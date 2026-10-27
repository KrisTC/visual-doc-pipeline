"""Tests for the test-runner command builder and the slow-test marker."""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

from scripts import run_tests
from slow_test_support import slow_test

FAST = run_tests.FAST_TESTS_ENVIRONMENT_VARIABLE


class DefaultWorkerCountTests(unittest.TestCase):
    # Verifies TR-2026-10-27-02.
    def test_leaves_two_cores_free_but_never_drops_below_one_worker(self) -> None:
        for cores, expected in ((16, 14), (8, 6), (4, 2), (3, 1), (2, 1), (1, 1)):
            with self.subTest(cores=cores):
                self.assertEqual(expected, run_tests.default_worker_count(cores))


class BuildCommandTests(unittest.TestCase):
    # Verifies TR-2026-10-27-02.
    def test_runs_pytest_in_parallel_by_default(self) -> None:
        command, environment = run_tests.build_command([], available_cores=8)

        self.assertEqual([sys.executable, "-m", "pytest", "-n", "6"], command)
        self.assertEqual({FAST: None}, environment)

    # Verifies TR-2026-10-27-02.
    def test_one_worker_runs_in_the_main_process(self) -> None:
        command, _ = run_tests.build_command([], available_cores=2)

        self.assertEqual(["-n", "0"], command[3:])

    # Verifies TR-2026-10-27-02.
    def test_worker_count_can_be_overridden(self) -> None:
        command, _ = run_tests.build_command(["--workers", "3"], available_cores=64)

        self.assertEqual(["-n", "3"], command[3:])

    # Verifies TR-2026-10-27-02.
    def test_rejects_a_worker_count_below_one(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            run_tests.build_command(["--workers", "0"], available_cores=8)

        self.assertEqual(2, raised.exception.code)

    # Verifies TR-2026-10-27-02.
    def test_serial_mode_uses_unittest_discovery_of_the_tests_directory(self) -> None:
        command, _ = run_tests.build_command(["--serial"], available_cores=8)

        self.assertEqual(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(run_tests.TESTS_DIRECTORY),
                "-p",
                "test_*.py",
            ],
            command,
        )

    # Verifies TR-2026-10-27-03.
    def test_forwards_unrecognised_arguments_to_the_active_runner(self) -> None:
        arguments = ["-k", "name pattern", "--durations", "5", "-v"]

        parallel, _ = run_tests.build_command(arguments, available_cores=8)
        serial, _ = run_tests.build_command(["--serial", *arguments], available_cores=8)

        self.assertEqual(arguments, parallel[5:])
        self.assertEqual(arguments, serial[-len(arguments) :])

    # Verifies TR-2026-10-27-03.
    def test_fast_option_sets_the_environment_variable_and_is_not_forwarded(self) -> None:
        for extra in ([], ["--serial"]):
            with self.subTest(extra=extra):
                command, environment = run_tests.build_command(
                    ["--fast", *extra], available_cores=8
                )

                self.assertEqual({FAST: "1"}, environment)
                self.assertNotIn("--fast", command)


class MainTests(unittest.TestCase):
    # Verifies TR-2026-10-27-03.
    def test_a_plain_run_clears_an_inherited_fast_setting_and_returns_the_exit_code(self) -> None:
        completed = MagicMock(returncode=7)
        with patch.dict(os.environ, {FAST: "1"}), patch(
            "scripts.run_tests.subprocess.run", return_value=completed
        ) as run:
            exit_code = run_tests.main(["--serial"])

        self.assertEqual(7, exit_code)
        self.assertNotIn(FAST, run.call_args.kwargs["env"])

    # Verifies TR-2026-10-27-03.
    def test_fast_run_passes_the_setting_to_the_test_process(self) -> None:
        completed = MagicMock(returncode=0)
        with patch.dict(os.environ, {}, clear=False), patch(
            "scripts.run_tests.subprocess.run", return_value=completed
        ) as run:
            os.environ.pop(FAST, None)
            run_tests.main(["--fast", "--serial"])

        self.assertEqual("1", run.call_args.kwargs["env"][FAST])


class SlowTestMarkerTests(unittest.TestCase):
    def _run_marked_test(self) -> unittest.TestResult:
        class Marked(unittest.TestCase):
            @slow_test
            def test_slow(self) -> None:
                pass

        return unittest.TextTestRunner(stream=io.StringIO()).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Marked)
        )

    # Verifies TR-2026-10-27-03.
    def test_skips_with_a_visible_reason_when_fast_is_requested(self) -> None:
        with patch.dict(os.environ, {FAST: "1"}):
            result = self._run_marked_test()

        self.assertEqual(1, len(result.skipped))
        self.assertIn("--fast", result.skipped[0][1])
        self.assertEqual(0, result.testsRun - len(result.skipped))

    # Verifies TR-2026-10-27-03.
    def test_runs_unchanged_when_fast_is_not_requested(self) -> None:
        with patch.dict(os.environ, {}):
            os.environ.pop(FAST, None)
            result = self._run_marked_test()

        self.assertEqual([], result.skipped)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(1, result.testsRun)


if __name__ == "__main__":
    unittest.main()
