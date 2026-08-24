# Technical Requirements

---

## Requirement Template

---

## FR-YYYY-MM-DD-NN

| Property | Value |
|----------|-------|
| Title | |
| Owner | |
| Status | Proposed |
| Source | |
| Date Added | YYYY-MM-DD |
| Related Requirements | |

### Description

Describe the capability that the system must provide.

### Rationale

Explain why this requirement exists and what problem it solves.

### Notes

Additional context, assumptions, constraints, unresolved questions, or implementation guidance.

---

## TR-2026-08-01-01

| Property | Value |
|----------|-------|
| Title | Python dependency management uses uv |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-01 |
| Related Requirements | |

### Description

The project shall use [uv](https://docs.astral.sh/uv/) for Python dependency management, dependency locking, and environment synchronisation. The initial supported Python interpreter version shall be 3.13.14.

### Rationale

Provides a single, defined dependency-management tool for Python development.

### Notes

Dependencies shall be declared in `pyproject.toml`, locked in `uv.lock`, and installed with `uv sync --locked`.

---

## TR-2026-08-01-02

| Property | Value |
|----------|-------|
| Title | Python libraries for document-file processing |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-01 |
| Related Requirements | TR-2026-08-01-01 |

### Description

The project shall use Python libraries to work with PDF, PowerPoint, Word, and Excel files.

### Rationale

The pipeline requires programmatic support for these document formats.

### Notes

The initial document libraries are `pypdf` (PDF), `python-pptx` (PowerPoint), `python-docx` (Word), `openpyxl` (Excel), and `Pillow` (raster-image decoding and encoding). Required document operations and validation criteria remain to be specified.

---

## TR-2026-08-01-03

| Property | Value |
|----------|-------|
| Title | Centralised test suite and runner |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-01 |
| Related Requirements | FR-2026-08-01-01, TR-2026-08-01-01 |

### Description

The project shall store automated tests in a top-level `tests/` directory. It shall provide platform test runners that discover and run the complete test suite:

- an executable Bash script at `scripts/run-tests.sh` for macOS and Linux
- a PowerShell script at `scripts/run-tests.ps1` for Windows

Both runners shall invoke the same test discovery command and shall be runnable from the repository root after the environment has been synchronised with uv.

### Rationale

A single test location and equivalent per-platform test commands make regression checks easy to find and run consistently on macOS, Linux, and Windows.

### Notes

Both runners shall use Python's standard-library `unittest` discovery against `tests/` with the pattern `test_*.py`. They shall exit with the underlying test-process exit code. Direct hard-coded paths into `.venv/bin` or `.venv/Scripts` shall not be required by the runners, so the same approach works across platforms.

FR-2026-08-24-03 supersedes this requirement's direct `uv run` invocation: each runner shall delegate its test command to the corresponding `scripts/run.ps1` or `scripts/run.sh` wrapper. That wrapper remains responsible for executing Python from the project's synchronised uv environment and loading the optional local `.env.local` configuration.

---


## TR-2026-08-01-04

| Property | Value |
|----------|-------|
| Title | Strict Python type checking |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-01 |
| Related Requirements | TR-2026-08-01-01, TR-2026-08-01-03 |

### Description

The project shall use mypy to type-check all Python product code, scripts, and tests. It shall provide `scripts/typecheck-python.py` to run the complete Python type check. A task that changes Python code is incomplete until this script passes.

Python code shall use precise type annotations. Use of `Any` is prohibited except at a narrowly scoped untyped or dynamically typed boundary where no more precise representation is available; each such use shall include an adjacent comment explaining the boundary and why a more precise type is unavailable.

### Rationale

Strong static typing detects integration errors before runtime and keeps the pipeline interfaces reliable as provider plugins are added.

### Notes

The mypy configuration is stored in `pyproject.toml`, the dependency is locked in `uv.lock`, and `scripts/typecheck-python.py` runs mypy across the `pipeline/`, `scripts/`, and `tests/` directories.

---

## TR-2026-08-03-01

| Property | Value |
|----------|-------|
| Title | Isolate folder-processor format handlers and shared helpers |
| Owner | |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-05 |

### Description

The folder processor shall delegate each processed format type to a separate Python module, so format-specific behaviour can evolve independently. Shared orchestration and common helpers shall live in separate modules rather than in a single file-specific handler.

Each format handler shall expose an in-memory processing path in addition to any path-based entry point. When a supported type is embedded within another supported document type, the enclosing handler shall invoke that embedded type's same in-memory handler directly. It shall not write an intermediate file solely to process that embedded value.

### Rationale

Format-specific replacement behaviour will need iterative development. Separate handlers make that work focused, while shared in-memory processing prevents duplicated behaviour and unnecessary disk I/O for embedded content.

### Notes

The initial module boundary needs confirmation: whether a “format type” means each individual extension (for example, PNG and JPEG separately) or a format family with a shared codec-oriented handler (for example, one raster-bitmap handler). The refactor shall preserve the current command-line behaviour, output formats, per-file isolation, progress reporting, and public folder-replacement API.

---
