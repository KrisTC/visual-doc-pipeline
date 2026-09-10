"""Load trusted provider packages from the fixed OCI plugin mount."""

from __future__ import annotations

import hashlib
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

MOUNTED_PLUGIN_DIRECTORY = Path("/plugins")


def discover_mounted_plugin_packages(
    kind: str, built_in_names: set[str]
) -> tuple[tuple[str, ModuleType], ...]:
    """Return trusted packages from ``/plugins/<kind>`` in stable name order.

    Mounted plugins are an explicit operator trust boundary.  This loader does
    not search ``PYTHONPATH`` or install dependencies; it only imports immediate
    Python-package directories below the fixed mount.
    """
    root = MOUNTED_PLUGIN_DIRECTORY / kind
    if not root.exists():
        return ()
    if not root.is_dir():
        raise RuntimeError(f"Mounted {kind} plugin configuration is not a directory.")

    resolved_root = root.resolve()
    discovered: list[tuple[str, ModuleType]] = []
    names = set(built_in_names)
    for candidate in sorted(root.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir():
            continue
        provider_name = candidate.name
        if provider_name in names:
            raise RuntimeError(
                f"Mounted {kind} plugin conflicts with provider {provider_name!r}."
            )
        package_file = candidate / "__init__.py"
        if not package_file.is_file() or not _is_below(package_file, resolved_root):
            raise RuntimeError(
                f"Mounted {kind} plugin {provider_name!r} is not a Python package."
            )
        discovered.append((provider_name, _load_package(kind, provider_name, package_file)))
        names.add(provider_name)
    return tuple(discovered)


def _is_below(path: Path, root: Path) -> bool:
    """Return whether a candidate resolves inside the fixed plugin mount."""
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _load_package(kind: str, provider_name: str, package_file: Path) -> ModuleType:
    """Import one trusted mounted package without adding a host path globally."""
    digest = hashlib.sha256(str(package_file.resolve()).encode("utf-8")).hexdigest()[:16]
    module_name = f"_visual_doc_pipeline_mounted_{kind}_{digest}"
    specification = spec_from_file_location(
        module_name,
        package_file,
        submodule_search_locations=[str(package_file.parent)],
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Could not load mounted {kind} plugin {provider_name!r}.")
    module = module_from_spec(specification)
    sys.modules[module_name] = module
    try:
        specification.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise RuntimeError(f"Could not load mounted {kind} plugin {provider_name!r}.") from None
    return module
