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

Dependency-policy validation shall require every locked non-default-registry package name and version to have at least one approved artifact record. The locked artifact URL need not match an approved artifact URL. Before an approved artifact may be installed, a project-owned verification workflow shall obtain that exact approved artifact and compare its streaming SHA-256 digest with the approved record. A missing record, mismatched name, version, or digest shall fail closed and prevent installation. The workflow shall install only the verified artifact; it shall not verify one download and later fetch a different artifact from the registry.

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

## SR-2026-08-24-01

| Property | Value |
|----------|-------|
| Title | Google Cloud Translation credentials and remote-data boundary |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-24-04, FR-2026-08-24-03 |

### Description

Google Cloud Translation provider configuration shall be supplied only through the repository-root `.env.local` dotenv file or through the invoking process environment. The `.env.local` file shall remain Git-ignored and shall not be committed. It shall contain `GOOGLE_APPLICATION_CREDENTIALS` with an absolute local path to the service-account credential JSON file, `GOOGLE_CLOUD_PROJECT`, and may contain `GOOGLE_CLOUD_TRANSLATION_LOCATION`.

The provider shall use Google Application Default Credentials from the service-account credential JSON file referenced by `GOOGLE_APPLICATION_CREDENTIALS`. The credential file shall be stored outside the repository or in a Git-ignored location; it shall not be committed, copied into generated artifacts, or written to logs. The provider and setup helper shall not create service accounts or credential files.

The provider shall not implement API-key authentication or read `GOOGLE_API_KEY`. A standard API key is not the supported credential for this provider because it does not identify an IAM principal for the Cloud Translation Advanced v3 API.

The service account shall be granted the Google Cloud Translation API User role (`roles/cloudtranslate.user`) on the configured project. In the Google Cloud role picker, the administrator shall search for and select **Cloud Translation API User**. It shall not select Cloud Translation API Viewer, Editor, or Admin. The provider shall use the credential only for pre-trained `translateText` operations and shall not create or manage Google Cloud resources.

Google documents that Cloud Translation request text is held briefly in memory to provide the service, is not used to train or improve its translation features, and is not made public or shared with third parties. The provider may transmit user-authorized replacement text and its source and target language tags to the configured Cloud Translation endpoint, subject to Google's [Data usage FAQ](https://docs.cloud.google.com/translate/data-usage) and the organization's applicable data-handling obligations.

The Google Cloud Translation provider may process confidential samples when the user requests it, because Google publishes the documented service terms and privacy protections cited above. It shall be excluded from automatic local evaluation, and errors and diagnostics shall not disclose request text, credential values, credential paths, authorization headers, API responses, or Google project identifiers.

### Rationale

Cloud translation requires an external trust boundary and credentials. Restricting configuration to the established local environment mechanism prevents accidental version control of secrets. Google's documented API data-use controls permit the provider to process user-authorized text, including confidential samples when the user requests that processing.

### Notes

The project shall provide a concise Google Cloud Translation setup guide. It shall direct a developer to obtain a service-account credential JSON file, store the file in an approved local folder outside the repository, and run `scripts/configure-google-cloud-translation.ps1` to validate the file and configure the provider. The script shall derive the default project ID from the credential file's `project_id` value. It shall direct the administrator to enable billing and the Cloud Translation API and assign the service account **Cloud Translation API User** (`roles/cloudtranslate.user`) through the project role picker. It shall link to Google's [Cloud Translation setup guide](https://docs.cloud.google.com/translate/docs/setup), [Cloud Translation authentication guide](https://docs.cloud.google.com/translate/docs/authentication), [Cloud Translation access-control guide](https://docs.cloud.google.com/translate/docs/access-control), [Application Default Credentials guide](https://docs.cloud.google.com/docs/authentication/provide-credentials-adc), [Cloud Translation API page](https://console.cloud.google.com/apis/library/translate.googleapis.com), and [Google Cloud billing page](https://console.cloud.google.com/billing). The guide shall not contain a project-specific URL, API key, credential file, access token, or service-account private-key value.

`.env.local` may set `GOOGLE_CLOUD_TRANSLATION_LOCATION` to a supported continental-European location, such as `europe-west1`. That setting selects Google's EU multi-regional endpoint; when it is absent, the provider uses the global endpoint. The EU endpoint keeps at-rest data and machine-learning processing within continental Europe; it does not remove the developer's responsibility to confirm that their organization approves the configured project, identity, location, and applicable Google Cloud service terms. The endpoint configuration shall follow Google's [Global and multi-regional endpoints documentation](https://docs.cloud.google.com/translate/docs/advanced/endpoints).

Automated tests shall use synthetic configuration values and mocked Google clients. They shall verify that missing or invalid service-account credential configuration fails without secret disclosure, that API-key-only configuration is rejected without a network request, and that the local-evaluation path cannot invoke the remote provider.

---
