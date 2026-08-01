# Security Requirements

## Requirement Template

---

## SR-YYYY-MM-DD-NN

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

## SR-2026-08-01-01

| Property | Value |
|----------|-------|
| Title | Dependency cooldown and source-build prevention |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-01 |
| Related Requirements | TR-2026-08-01-01, TR-2026-08-01-02 |

### Description

The project shall configure uv to exclude registry distribution artifacts uploaded within the preceding seven days when resolving direct and transitive dependencies. Dependency installation shall not build source distributions. Third-party Git, direct-URL, local-path, and editable dependencies shall be prohibited by default.

### Rationale

A dependency cooldown gives the wider community time to detect and respond to a newly published malicious package or release. Preventing source-distribution builds prevents dependency build backends from running during installation.

### Notes

uv enforces the cooldown through `exclude-newer = "7 days"` and prevents source-distribution builds through `no-build = true`. Dependencies are restricted to the PyPI registry; a repository validation script rejects prohibited source types in project metadata and the lockfile. `no-build` may prevent installation of dependencies that do not provide a compatible wheel.

---
