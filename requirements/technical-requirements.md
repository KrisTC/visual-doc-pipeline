# Technical Requirements

---

## Requirement Template

---

## FR-YYYY-MM-DD-NN

| Property | Value |
|----------|-------|
| Title | |
| Owner | KrisTC |
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

## TR-2026-08-26-01

| Property | Value |
|----------|-------|
| Title | Dependency policy validation remains dependency-agnostic |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-26 |
| Related Requirements | SR-2026-08-01-01, SR-2026-08-21-02 |

### Description

`scripts/check-dependency-policy.py` shall remain dependency-agnostic. It shall derive registry configuration and package-to-index assignments from `pyproject.toml`, and approved non-default package versions from `approved-dependency-artifact-hashes.toml`. It shall not encode package names, package versions, security-requirement IDs, registry URLs, artifact hosts, or artifact paths for a particular dependency.

### Rationale

Dependency-specific validation causes routine publisher hosting changes to require code changes and makes registry-exception controls difficult to reuse.

### Notes

The checker validates metadata relationships. The verified-installation workflow remains responsible for downloading the approved artifact and verifying its SHA-256 digest before installation.

---

## TR-2026-08-01-01

| Property | Value |
|----------|-------|
| Title | Python dependency management uses uv |
| Owner | KrisTC |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
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

## TR-2026-08-29-01

| Property | Value |
|----------|-------|
| Title | Local PDFium renderer for outlined-PDF-text OCR |
| Owner | KrisTC |
| Status | Implemented |
| Source | User-approved renderer decision for FR-2026-08-29-01 |
| Date Added | 2026-08-29 |
| Related Requirements | FR-2026-08-29-01, SR-2026-08-29-01, TR-2026-08-01-01 |

### Description

The project shall use `pypdfium2==5.13.0` from PyPI as its local PDF renderer
for FR-2026-08-29-01. The adapter shall render one PDF page at a time at 200
DPI into an in-memory RGB bitmap. It shall support macOS, Windows, and Linux
only where this exact package version supplies a compatible pre-built wheel
for the project's pinned Python version and platform.

The PDF adapter shall provide a render input containing vector-painted page
content while excluding native PDF text and embedded raster images that its
existing replacement paths own. It shall map OCR polygons between the 200-DPI
render and PDF user-space coordinates without writing an intermediate document
or image file.

Before rendering a page, the adapter shall inspect that filtered content for
potentially visible vector path-painting or shading operations, recursively
following Form XObjects. A page with none shall not invoke PDFium or the OCR
provider. This inspection is conservative: a positive result authorizes the
bounded render and OCR pass but does not assert that the page contains text.

### Rationale

PDFium provides a local, deterministic renderer for vector outlines that pypdf
does not rasterize. An isolated render input prevents the new pass from
detecting and replacing the same visible text that native-PDF or embedded-image
processing already handles.

### Notes

The package version is older than the repository's mandatory seven-day PyPI
cooldown at the time of approval. Installation remains subject to the normal
PyPI-only, no-source-build, lockfile, and dependency-policy checks.

Automated tests shall mock the rendering boundary where rendering output is not
under test. Integration tests that exercise PDFium shall use synthetic PDFs and
verify the 200-DPI page-to-user-space coordinate conversion.

---

## TR-2026-08-29-02

| Property | Value |
|----------|-------|
| Title | One-pass PDFium virtual-text detection for undecodable native PDF text |
| Owner | KrisTC |
| Status | Proposed |
| Source | User-approved design for FR-2026-08-29-02 |
| Date Added | 2026-08-31 |
| Related Requirements | FR-2026-08-29-01, FR-2026-08-29-02, SR-2026-08-29-01 |

### Description

The PDF adapter shall construct one in-memory PDFium detection render per
eligible page for the combined vector-outline and undecodable-native-text OCR
paths. It shall clone only submitted PDF bytes, remove embedded raster images,
remove successfully rewritten native text, retain eligible undecodable text
showing operations with the state needed to paint them, and retain vector
painting and its visual context. It shall invoke the selected OCR provider at
most once for that render.

The adapter shall convert every accepted OCR result to a virtual visual-text
item with OCR text and finite page-space geometry. It shall not attempt to map
that item to a particular undecodable source operation. It shall merge virtual
and decoded native items only through the existing compatible visual-flow
inference; any item that cannot be merged safely remains an independent flow.
The replacement provider shall receive only the resulting flows.

### Rationale

Combining detection avoids an expensive second OCR request. Virtual text
recovers translation context without relying on undecodable PDF operands as
text or requiring a brittle per-operation OCR match.

### Notes

The render remains a transient in-memory input; it is never an output page.
Tests shall use synthetic PDFs and mocked OCR calls to verify one request per
page, filtering of decoded native and bitmap text, virtual-flow merging, and
the safe independent-flow fallback.

---
