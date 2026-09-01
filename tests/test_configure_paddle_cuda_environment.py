#!/usr/bin/env python3
"""Tests for Windows Paddle CUDA dotenv setup."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).parents[1]
MANAGED_MARKER = "# Managed by scripts/configure-paddle-cuda-environment.ps1"


@unittest.skipUnless(os.name == "nt", "Paddle CUDA setup script requires Windows.")
class ConfigurePaddleCudaEnvironmentTests(unittest.TestCase):
    """Verify setup without requiring NVIDIA software or PaddlePaddle."""

    # Verifies FR-2026-08-24-03.
    def test_discovers_environment_paths_and_preserves_user_entries(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script = _copy_setup_script(root)
            cuda_older_root, cuda_root, cudnn_root, _ = _create_runtime_directories(root)
            captured_candidate = root / "candidate.env"
            _write_fake_run_wrapper(root, captured_candidate)
            env_file = root / ".env.local"
            env_file.write_text("PROVIDER_TOKEN=synthetic-token\n", encoding="utf-8")

            completed_process = _run_setup(
                script,
                {
                    "CUDA_PATH_V12_0": str(cuda_older_root),
                    "CUDA_PATH_V12_8": str(cuda_root),
                    "CUDNN_PATH": str(cudnn_root),
                    "FAKE_PADDLE_PROBE_RESULT": 'PADDLE_GPU_PROBE={"compiled_with_cuda": true, "device_count": 1}',
                    "FAKE_PADDLE_CANDIDATE_FILE": str(captured_candidate),
                },
            )

            self.assertEqual(0, completed_process.returncode, completed_process.stderr)
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("PROVIDER_TOKEN=synthetic-token\n", content)
            self.assertIn(MANAGED_MARKER, content)
            managed_path = next(line for line in content.splitlines() if line.startswith("PATH="))
            self.assertIn('"', managed_path)
            self.assertIn("/cuda/v12.8/bin;", managed_path.lower())
            self.assertIn('/cudnn/v9.24/bin/12.9/x64;${path}"', managed_path.lower())
            self.assertEqual(content, captured_candidate.read_text(encoding="utf-8"))
            self.assertNotIn("synthetic-token", completed_process.stdout + completed_process.stderr)

    # Verifies FR-2026-08-24-03.
    def test_failed_probe_keeps_existing_environment_file_unchanged(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script = _copy_setup_script(root)
            cuda_older_root, cuda_root, cudnn_root, _ = _create_runtime_directories(root)
            captured_candidate = root / "candidate.env"
            _write_fake_run_wrapper(root, captured_candidate)
            env_file = root / ".env.local"
            original_content = "PROVIDER_TOKEN=synthetic-token\n"
            env_file.write_text(original_content, encoding="utf-8")

            completed_process = _run_setup(
                script,
                {
                    "CUDA_PATH_V12_0": str(cuda_older_root),
                    "CUDA_PATH_V12_8": str(cuda_root),
                    "CUDNN_PATH": str(cudnn_root),
                    "FAKE_PADDLE_PROBE_RESULT": 'PADDLE_GPU_PROBE={"compiled_with_cuda": false, "device_count": 0}',
                    "FAKE_PADDLE_CANDIDATE_FILE": str(captured_candidate),
                },
            )

            self.assertNotEqual(0, completed_process.returncode)
            self.assertEqual(original_content, env_file.read_text(encoding="utf-8"))
            self.assertEqual([], list(root.glob(".env.local.*.tmp")))
            self.assertNotIn("synthetic-token", completed_process.stdout + completed_process.stderr)


def _copy_setup_script(root: Path) -> Path:
    """Copy the setup script into an isolated synthetic project root."""
    scripts_directory = root / "scripts"
    scripts_directory.mkdir()
    destination = scripts_directory / "configure-paddle-cuda-environment.ps1"
    shutil.copy2(PROJECT_ROOT / "scripts" / destination.name, destination)
    return destination


def _create_runtime_directories(root: Path) -> tuple[Path, Path, Path, Path]:
    """Create ordered CUDA 12.x and cuDNN 9.x Windows x64 runtimes."""
    cuda_older_root = root / "cuda" / "v12.0"
    cuda_root = root / "cuda" / "v12.8"
    for cuda_directory in (cuda_older_root, cuda_root):
        cuda_bin = cuda_directory / "bin"
        cuda_bin.mkdir(parents=True)
        (cuda_bin / "cudart64_12.dll").touch()
    cudnn_root = root / "cudnn"
    for cudnn_version, runtime_version in (("v9.23", "12.7"), ("v9.24", "12.9")):
        cudnn_bin = cudnn_root / cudnn_version / "bin" / runtime_version / "x64"
        cudnn_bin.mkdir(parents=True)
        (cudnn_bin / "cudnn64_9.dll").touch()
    return cuda_older_root, cuda_root, cudnn_root, cudnn_root / "v9.24" / "bin" / "12.9" / "x64"


def _write_fake_run_wrapper(root: Path, captured_candidate: Path) -> None:
    """Write a wrapper that captures the temporary dotenv and returns a mock probe."""
    wrapper = root / "run.ps1"
    wrapper.write_text(
        "param()\r\n"
        "$envFile = $args[1]\r\n"
        "[System.IO.File]::WriteAllText($env:FAKE_PADDLE_CANDIDATE_FILE, [System.IO.File]::ReadAllText($envFile))\r\n"
        "Write-Output $env:FAKE_PADDLE_PROBE_RESULT\r\n"
        "exit 0\r\n",
        encoding="ascii",
    )
    assert captured_candidate.parent == root


def _run_setup(script: Path, extra_environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run one setup-script invocation with synthetic discovery and probe inputs."""
    return subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script)],
        check=False,
        capture_output=True,
        env={**os.environ, **extra_environment},
        text=True,
    )


if __name__ == "__main__":
    unittest.main()
