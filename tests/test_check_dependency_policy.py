"""Tests for generic dependency-policy validation."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "check-dependency-policy.py"
_SPECIFICATION = importlib.util.spec_from_file_location("check_dependency_policy", _SCRIPT_PATH)
assert _SPECIFICATION is not None and _SPECIFICATION.loader is not None
policy = importlib.util.module_from_spec(_SPECIFICATION)
sys.modules[_SPECIFICATION.name] = policy
_SPECIFICATION.loader.exec_module(policy)


class DependencyPolicyTests(unittest.TestCase):
    # Verifies TR-2026-08-26-01 and SR-2026-08-21-02.
    def test_allows_a_locked_non_default_package_with_an_approved_version(self) -> None:
        errors: list[str] = []
        configuration = policy.validate_pyproject(_pyproject(), errors)

        policy.validate_lockfile(
            _lockfile("https://artifacts.changed-host.example/demo_package-1.2.3-cp313-cp313-win_amd64.whl"),
            "demo-project",
            configuration,
            {("demo-package", "1.2.3")},
            errors,
        )

        self.assertEqual([], errors)

    # Verifies TR-2026-08-26-01 and SR-2026-08-21-02.
    def test_rejects_a_locked_non_default_package_without_an_approved_version(self) -> None:
        errors: list[str] = []
        configuration = policy.validate_pyproject(_pyproject(), errors)

        policy.validate_lockfile(
            _lockfile("https://artifacts.changed-host.example/demo_package-1.2.3-cp313-cp313-win_amd64.whl"),
            "demo-project",
            configuration,
            set(),
            errors,
        )

        self.assertEqual(["uv.lock: demo-package==1.2.3 has no approved verified artifact."], errors)

    # Verifies TR-2026-08-26-01.
    def test_rejects_a_non_default_registry_not_configured_by_pyproject(self) -> None:
        errors: list[str] = []
        configuration = policy.validate_pyproject(_pyproject(), errors)
        lockfile = _lockfile("https://artifacts.example/demo_package-1.2.3-cp313-cp313-win_amd64.whl")
        package = lockfile["package"]
        assert isinstance(package, list)
        package[0]["source"] = {"registry": "https://other-registry.example/simple/"}

        policy.validate_lockfile(lockfile, "demo-project", configuration, {("demo-package", "1.2.3")}, errors)

        self.assertEqual(["uv.lock: 'demo-package' uses an unconfigured non-default registry."], errors)

    # Verifies TR-2026-08-26-01.
    def test_success_message_summarizes_generic_validation_activity(self) -> None:
        message = policy.success_message(
            policy.IndexConfiguration("https://default.example/simple/", {"demo": "https://registry.example/simple/"}, {}),
            policy.LockfileValidation(12, 1),
            policy.ApprovedArtifacts({("demo-package", "1.2.3")}, 2),
        )

        self.assertEqual(
            "Dependency policy check passed.\n"
            "- Source controls: exclude-newer=7 days, no-build=True, package=False.\n"
            "- Registries: 1 default and 1 explicit configured.\n"
            "- Lockfile: 12 registry packages checked, including 1 from explicit registries.\n"
            "- Approved artifacts: 2 wheel records cover 1 non-default package versions.",
            message,
        )


def _pyproject() -> dict[str, object]:
    return {
        "project": {"dependencies": ["demo-package==1.2.3"]},
        "tool": {
            "uv": {
                "exclude-newer": "7 days",
                "no-build": True,
                "package": False,
                "sources": {"demo-package": {"index": "demo-registry"}},
                "index": [
                    {"name": "demo-registry", "url": "https://registry.example/simple/", "explicit": True},
                    {"name": "default", "url": "https://default.example/simple/", "default": True},
                ],
            }
        },
    }


def _lockfile(wheel_url: str) -> dict[str, object]:
    return {
        "package": [
            {
                "name": "demo-package",
                "version": "1.2.3",
                "source": {"registry": "https://registry.example/simple/"},
                "wheels": [{"url": wheel_url}],
            }
        ]
    }