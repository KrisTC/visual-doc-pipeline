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
| Related Requirements | FR-2026-08-01-01 |

### Description

The project shall store automated tests in a top-level `tests/` directory. It shall provide an executable Bash script at `scripts/run-tests.sh` that discovers and runs the complete test suite.

### Rationale

A single test location and test command make regression checks easy to find and run consistently.

### Notes

The runner shall use the project's synchronised virtual environment and Python's standard-library `unittest` discovery.

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
