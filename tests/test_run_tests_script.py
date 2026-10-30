"""Tests for the test-runner command builder and the slow-test marker."""

from __future__ import annotations

import io
import os
import sys
import unittest
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

        self.assertEqual([sys.executable, "-m", "pytest", "-n", "6", "--dist=worksteal"], command)
        self.assertEqual({FAST: None}, environment)

    # Verifies TR-2026-10-27-02.
    def test_one_worker_runs_in_the_main_process(self) -> None:
        command, _ = run_tests.build_command([], available_cores=2)

        self.assertEqual(["-n", "0", "--dist=worksteal"], command[3:])

    # Verifies TR-2026-10-30-01.
    def test_selected_items_limit_workers(self) -> None:
        for count, expected in ((0, 0), (1, 0), (2, 0), (3, 2), (8, 4), (99, 6)):
            with self.subTest(count=count):
                command, _ = run_tests.build_command([], available_cores=8, selected_items=count)
                self.assertEqual(["-n", str(expected), "--dist=worksteal"], command[3:])

    # Verifies TR-2026-10-30-01.
    def test_selectors_trigger_collection_but_general_options_do_not(self) -> None:
        for args in (["-k", "name"], ["-m", "slow"], ["tests/test_pdf_plan.py::test_x"], ["tests"]):
            with self.subTest(args=args):
                self.assertTrue(run_tests._has_selection(args))
        self.assertFalse(run_tests._has_selection(["--durations", "20", "-v"]))

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

        self.assertEqual(arguments, parallel[6:])
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
    # Verifies TR-2026-10-30-01.
    def test_focused_run_sizes_workers_from_collection(self) -> None:
        collection = MagicMock(returncode=0, stdout="collected\n3\n", stderr="")
        completed = MagicMock(returncode=0)
        with patch("scripts.run_tests._available_cores", return_value=8), patch(
            "scripts.run_tests.subprocess.run", side_effect=[collection, completed]
        ) as run:
            self.assertEqual(0, run_tests.main(["-k", "example"]))
        self.assertEqual(["-n", "2", "--dist=worksteal", "-k", "example"], run.call_args.args[0][3:])

    # Verifies TR-2026-10-30-01.
    def test_collection_failure_is_returned_without_running_tests(self) -> None:
        collection = MagicMock(returncode=4, stdout="collection failed\n", stderr="")
        with patch("scripts.run_tests.subprocess.run", return_value=collection) as run, patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            self.assertEqual(4, run_tests.main(["tests/missing.py"]))
        self.assertEqual(1, run.call_count)

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
