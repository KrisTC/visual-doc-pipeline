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

## SR-2026-08-21-02

| Property | Value |
|----------|-------|
| Title | Approved registry exceptions and artifact verification |
| Owner | |
| Status | Implemented |
| Source | User request to make non-default registry controls reusable |
| Date Added | 2026-08-21 |
| Related Requirements | SR-2026-08-01-01 |

### Description

A requirement that explicitly permits a non-default package registry may define an exception only for named distributions, exact versions, and named registry URLs. It shall not implicitly permit other distributions, versions, indexes, direct URLs, Git dependencies, local-path dependencies, editable dependencies, or source distributions.

The repository shall store the approved SHA-256 digest for every wheel artifact permitted by such an exception in the root-level `approved-dependency-artifact-hashes.toml` security-control file. Approving a distribution version shall approve the complete set of wheel siblings for that distribution and version whose Python tags are compatible with the project's declared Python version, across every platform the authorizing registry provides for those tags. Each record shall identify exactly one authorizing security-requirement ID, distribution name, version, artifact URL, and SHA-256 digest. The authorizing requirement must explicitly permit that artifact. The file shall contain no artifact record that no implemented or approved security requirement permits.

Dependency-policy validation shall require every locked non-default-registry artifact URL to match one approved record. Before an approved artifact may be installed, a project-owned verification workflow shall obtain that exact artifact and compare its streaming SHA-256 digest with the approved record. A missing record, mismatched name, version, URL, or digest shall fail closed and prevent installation. The workflow shall install only the verified artifact; it shall not verify one download and later fetch a different artifact from the registry.

The workflow shall derive artifact URLs from the authorizing registry's PEP 503 simple-index page for the requested normalized distribution name. Its user-facing inputs shall be the authorizing requirement ID, registry base URL, distribution name, and exact version. It shall derive the supported CPython tags from the project `requires-python` declaration, select every wheel whose filename declares the requested version and one of those tags, reject source distributions and direct artifact URLs supplied as inputs, and fail when it finds no eligible wheels. It shall download and verify every selected wheel before writing its approved-hash record. It shall persist each verified record immediately and retain incomplete downloads in a gitignored local cache so an interrupted run resumes completed records and, where the registry supports HTTP range requests, partial wheel bytes. The discovered artifact URLs, wheel tags, sizes, and SHA-256 digests shall be displayed for human review.

### Rationale

Some platform-specific dependencies are not published on PyPI or do not publish compatible artifact hashes. A narrow exception and locally reviewed artifact digest maintain the default dependency restrictions while providing a reusable integrity control for explicitly approved cases.

### Notes

The approved-hash file is a custom project security-control input, rather than a uv configuration file. Updating an approved digest requires human review of the corresponding artifact, its exact source URL, and its authorizing security requirement. The file shall not contain credentials, confidential sample data, or executable code.

An exception requirement shall state whether the standard seven-day cooldown applies to its registry. If the registry does not publish reliable upload timestamps, that exception must expressly justify an alternative control before the registry can be used.

The artifact-approval and verified-installation workflows shall use `tqdm` byte-progress bars while downloading an artifact. Each bar shall identify the artifact filename, use the registry's declared content length when available, and remain usable when that length is absent.

---

## SR-2026-08-21-01

| Property | Value |
|----------|-------|
| Title | Official Paddle CUDA wheel registry exception |
| Owner | |
| Status | Implemented |
| Source | User-approved exception for opportunistic NVIDIA GPU OCR acceleration |
| Date Added | 2026-08-21 |
| Related Requirements | SR-2026-08-01-01, SR-2026-08-21-02, FR-2026-08-21-01 |

### Description

This requirement explicitly permits the project to resolve the `paddlepaddle-gpu` distribution from PaddlePaddle's official CUDA 12.6 simple index at `https://www.paddlepaddle.org.cn/packages/stable/cu126/`. This permission is limited to the distribution and registry named by this requirement.

The exception permits only an exact pinned `paddlepaddle-gpu` version represented in `pyproject.toml` and `uv.lock`. It shall use the generic exception and verification controls defined by SR-2026-08-21-02.

### Rationale

PaddleOCR can use an NVIDIA GPU for local inference, but PaddlePaddle publishes its Windows CUDA wheels through its official CUDA-specific package index rather than PyPI. The repository requires a CUDA-enabled PaddlePaddle wheel for automatic GPU selection while retaining reproducible dependency resolution and the existing restrictive dependency policy.

### Notes

The existing seven-day artifact cooldown remains mandatory for every PyPI-sourced package. The Paddle registry exception is limited to the approved, exact `paddlepaddle-gpu` distribution because that registry does not expose PyPI-compatible publication timestamps for enforcing the same cooldown.

The existing seven-day artifact cooldown remains mandatory for every PyPI-sourced package. This exception authorizes `paddlepaddle-gpu==3.3.1` from the named Paddle index despite its lack of reliable upload timestamps, with SR-2026-08-21-02's locally approved SHA-256 verification as the alternative integrity control.

---

## SR-2026-08-03-02

| Property | Value |
|----------|-------|
| Title | Do not dereference external resources from vector graphics |
| Owner | |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-10, FR-2026-08-03-11, FR-2026-08-03-12 |

### Description

Vector processing shall not fetch, open, or otherwise dereference an external URL, filesystem path, package-relative path, or network resource referenced by a vector graphic. Only bytes contained within the submitted standalone graphic or Office package part may be processed.

### Rationale

External resource references create network and filesystem disclosure paths, non-deterministic output, and server-side request forgery risk when graphics are processed automatically.

### Notes

An SVG `data:` URI is self-contained data, not an external resource, and is permitted only for the supported bitmap MIME types defined by the corresponding feature requirement. Unsupported external references remain unchanged and must not be logged with their target value.

---
