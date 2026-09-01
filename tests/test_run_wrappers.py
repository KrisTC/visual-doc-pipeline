#!/usr/bin/env python3
"""Tests for the project-local Python launcher wrappers."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).parents[1]


class RunPowerShellWrapperTests(unittest.TestCase):
    """Verify the PowerShell wrapper with a synthetic uv executable."""

    # Verifies FR-2026-08-24-03.
    @unittest.skipUnless(os.name == "nt", "PowerShell wrapper requires Windows.")
    def test_uses_local_or_explicit_dotenv_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            wrapper = _copy_root_script(root, "run.ps1")
            arguments_file = root / "uv-arguments.txt"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "uv.cmd").write_text(
                "@echo off\r\n"
                "> \"%RUN_WRAPPER_ARGUMENTS_FILE%\" echo %*\r\n"
                "exit /b 0\r\n",
                encoding="ascii",
            )
            environment = _wrapper_environment(fake_bin, arguments_file)

            _run_power_shell(wrapper, environment, "-c", "pass")
            self.assertEqual("run python -c pass", _read_arguments(arguments_file))

            local_env_file = root / ".env.local"
            local_env_file.write_text("PROVIDER_TOKEN=synthetic\n", encoding="utf-8")
            _run_power_shell(wrapper, environment, "-c", "pass")
            arguments = _read_arguments(arguments_file)
            self.assertTrue(arguments.startswith("run --env-file=C:/"))
            self.assertNotIn("\\", arguments)
            self.assertTrue(arguments.endswith("/.env.local python -c pass"))

            override_env_file = root / "candidate.env"
            override_env_file.write_text("PATH=synthetic\n", encoding="utf-8")
            _run_power_shell(
                wrapper,
                environment,
                "-EnvFile",
                str(override_env_file),
                "-c",
                "pass",
            )
            arguments = _read_arguments(arguments_file)
            self.assertTrue(arguments.startswith("run --env-file=C:/"))
            self.assertNotIn("\\", arguments)
            self.assertTrue(arguments.endswith("/candidate.env python -c pass"))

    # Verifies FR-2026-08-24-03.
    @unittest.skipUnless(os.name == "nt", "PowerShell wrapper requires Windows.")
    def test_test_runner_delegates_to_the_wrapper(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            test_runner = _copy_script(root, "run-tests.ps1")
            _copy_root_script(root, "run.ps1")
            arguments_file = root / "uv-arguments.txt"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "uv.cmd").write_text(
                "@echo off\r\n"
                "> \"%RUN_WRAPPER_ARGUMENTS_FILE%\" echo %*\r\n"
                "exit /b 0\r\n",
                encoding="ascii",
            )

            _run_power_shell(test_runner, _wrapper_environment(fake_bin, arguments_file))

            arguments = _read_arguments(arguments_file)
            self.assertTrue(arguments.startswith("run python -m unittest discover -s "))
            self.assertTrue(arguments.endswith("\\tests -p test_*.py"))

    # Verifies FR-2026-08-24-03.
    @unittest.skipUnless(os.name == "nt", "PowerShell wrapper requires Windows.")
    def test_applies_the_marked_dotenv_path_before_invoking_uv(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            wrapper = _copy_root_script(root, "run.ps1")
            path_file = root / "uv-path.txt"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "uv.cmd").write_text(
                "@echo off\r\n"
                "> \"%RUN_WRAPPER_PATH_FILE%\" echo %PATH%\r\n"
                "exit /b 0\r\n",
                encoding="ascii",
            )
            (root / ".env.local").write_text(
                "# Managed by scripts/configure-paddle-cuda-environment.ps1\n"
                'PATH="C:/synthetic/cuda;C:/synthetic/cudnn;${PATH}"\n',
                encoding="ascii",
            )
            environment = {
                **_wrapper_environment(fake_bin, root / "unused.txt"),
                "RUN_WRAPPER_PATH_FILE": str(path_file),
            }

            _run_power_shell(wrapper, environment, "-c", "pass")

            recorded_path = path_file.read_text(encoding="utf-8").strip()
            self.assertTrue(recorded_path.startswith("C:/synthetic/cuda;C:/synthetic/cudnn;"))


class RunBashWrapperTests(unittest.TestCase):
    """Verify the Bash wrapper with a synthetic uv executable."""

    # Verifies FR-2026-08-24-03.
    @unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "Bash wrapper requires a Unix host.")
    def test_uses_local_or_explicit_dotenv_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            wrapper = _copy_root_script(root, "run.sh")
            arguments_file = root / "uv-arguments.txt"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$@\" > \"${RUN_WRAPPER_ARGUMENTS_FILE}\"\n",
                encoding="utf-8",
            )
            fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)
            environment = _wrapper_environment(fake_bin, arguments_file)

            _run_bash(wrapper, environment, "-c", "pass")
            self.assertEqual(("run", "python", "-c", "pass"), _read_argument_lines(arguments_file))

            local_env_file = root / ".env.local"
            local_env_file.write_text("PROVIDER_TOKEN=synthetic\n", encoding="utf-8")
            _run_bash(wrapper, environment, "-c", "pass")
            self.assertEqual(
                ("run", "--env-file", str(local_env_file), "python", "-c", "pass"),
                _read_argument_lines(arguments_file),
            )

            override_env_file = root / "candidate.env"
            override_env_file.write_text("PATH=synthetic\n", encoding="utf-8")
            _run_bash(
                wrapper,
                environment,
                "--env-file",
                str(override_env_file),
                "--",
                "-c",
                "pass",
            )
            self.assertEqual(
                ("run", "--env-file", str(override_env_file), "python", "-c", "pass"),
                _read_argument_lines(arguments_file),
            )


def _copy_script(root: Path, script_name: str) -> Path:
    """Copy one project script into an isolated synthetic project root."""
    scripts_directory = root / "scripts"
    scripts_directory.mkdir(exist_ok=True)
    destination = scripts_directory / script_name
    shutil.copy2(PROJECT_ROOT / "scripts" / script_name, destination)
    return destination


def _copy_root_script(root: Path, script_name: str) -> Path:
    """Copy one repository-root launcher into an isolated project root."""
    destination = root / script_name
    shutil.copy2(PROJECT_ROOT / script_name, destination)
    if script_name.endswith(".sh"):
        destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
    return destination


def _wrapper_environment(fake_bin: Path, arguments_file: Path) -> dict[str, str]:
    """Build an environment in which the synthetic uv executable wins lookup."""
    return {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "RUN_WRAPPER_ARGUMENTS_FILE": str(arguments_file),
    }


def _run_power_shell(wrapper: Path, environment: dict[str, str], *arguments: str) -> None:
    """Run one PowerShell wrapper invocation and require success."""
    completed_process = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(wrapper), *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if completed_process.returncode != 0:
        raise AssertionError(completed_process.stderr)


def _run_bash(wrapper: Path, environment: dict[str, str], *arguments: str) -> None:
    """Run one Bash wrapper invocation and require success."""
    completed_process = subprocess.run(
        [str(wrapper), *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if completed_process.returncode != 0:
        raise AssertionError(completed_process.stderr)


def _read_arguments(path: Path) -> str:
    """Read one synthetic Windows command-line record."""
    return path.read_text(encoding="utf-8").strip()


def _read_argument_lines(path: Path) -> tuple[str, ...]:
    """Read one synthetic Unix argv record."""
    return tuple(path.read_text(encoding="utf-8").splitlines())


if __name__ == "__main__":
    unittest.main()
