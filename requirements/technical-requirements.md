# Technical Requirements

---

## Requirement Template

---

## FR-YYYY-MM-DD-NN

| Property | Value |
|----------|-------|
| Title | |
| Owner | |
| Status | Implemented |
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

The project shall use [uv](https://docs.astral.sh/uv/) for Python dependency management, dependency locking, and environment synchronisation. The initial supported Python interpreter version shall be 3.14.6.

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

The initial document libraries are `pypdf` (PDF), `python-pptx` (PowerPoint), `python-docx` (Word), and `openpyxl` (Excel). Required document operations and validation criteria remain to be specified.

---
