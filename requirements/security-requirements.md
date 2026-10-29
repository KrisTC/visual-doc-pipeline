# Security Requirements

## Requirement Template

---

## SR-YYYY-MM-DD-NN

| Property | Value |
|----------|-------|
| Title | |
| Owner | KrisTC |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
| Status | Implemented |
| Source | User request to make non-default registry controls reusable |
| Date Added | 2026-08-21 |
| Related Requirements | SR-2026-08-01-01 |

### Description

A requirement that explicitly permits a non-default package registry may define an exception only for named distributions, exact versions, and named registry URLs. It shall not implicitly permit other distributions, versions, indexes, direct URLs, Git dependencies, local-path dependencies, editable dependencies, or source distributions.

The repository shall store the approved SHA-256 digest for every wheel artifact permitted by such an exception in the root-level `approved-dependency-artifact-hashes.toml` security-control file. Approving a distribution version shall approve the complete set of wheel siblings for that distribution and version whose Python tags are compatible with the project's declared Python version, across every platform the authorizing registry provides for those tags. Each record shall identify exactly one authorizing security-requirement ID, distribution name, version, artifact URL, and SHA-256 digest. The authorizing requirement must explicitly permit that artifact. The file shall contain no artifact record that no implemented or approved security requirement permits.

Dependency-policy validation shall require every locked non-default-registry package name and version to have at least one approved artifact record. The locked artifact URL need not match an approved artifact URL. Before an approved artifact may be installed, a project-owned verified-installation workflow shall generate a transient, non-user-editable requirements input from its matching approved artifact record. Each generated requirement shall identify the exact approved wheel URL and its approved SHA-256 digest. The workflow shall invoke uv to download and install that input with `--require-hashes`, `--no-deps`, and `--no-index`. uv's hash check shall fail closed before installation. A missing record, mismatched name, version, or digest, source distribution, unapproved artifact, or attempt to resolve an additional dependency shall prevent installation.

The workflow shall derive artifact URLs from the authorizing registry's PEP 503 simple-index page for the requested normalized distribution name. Its user-facing inputs shall be the authorizing requirement ID, registry base URL, distribution name, and exact version. It shall derive the supported CPython tags from the project `requires-python` declaration, select every wheel whose filename declares the requested version and one of those tags, reject source distributions and direct artifact URLs supplied as inputs, and fail when it finds no eligible wheels. It shall download and verify every selected wheel before writing its approved-hash record. It shall persist each verified record immediately and retain incomplete downloads in a gitignored local cache so an interrupted run resumes completed records and, where the registry supports HTTP range requests, partial wheel bytes. The discovered artifact URLs, wheel tags, sizes, and SHA-256 digests shall be displayed for human review.

### Rationale

Some platform-specific dependencies are not published on PyPI or do not publish compatible artifact hashes. A narrow exception and locally reviewed artifact digest maintain the default dependency restrictions while providing a reusable integrity control for explicitly approved cases.

### Notes

The approved-hash file is a custom project security-control input, rather than a uv configuration file. Updating an approved digest requires human review of the corresponding artifact, its exact source URL, and its authorizing security requirement. The file shall not contain credentials, confidential sample data, or executable code.

An exception requirement shall state whether the standard seven-day cooldown applies to its registry. If the registry does not publish reliable upload timestamps, that exception must expressly justify an alternative control before the registry can be used.

The artifact-approval workflow's download progress is defined by
FR-2026-09-03-01. The verified-installation workflow delegates download
progress to uv because uv performs the download and hash verification.
Verified-installation tests shall use synthetic artifacts and verify that the
generated uv command requires hashes, disables index and dependency resolution,
and supplies a mismatched digest to uv before it can install the artifact.

---

## SR-2026-08-21-01

| Property | Value |
|----------|-------|
| Title | Official Paddle CUDA wheel registry exception |
| Owner | KrisTC |
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

## SR-2026-09-08-01

| Property | Value |
|----------|-------|
| Title | Official PyTorch CPU wheel registry exception |
| Owner | KrisTC |
| Status | Implemented |
| Source | User-approved CPU OCI image dependency decision |
| Date Added | 2026-09-08 |
| Related Requirements | SR-2026-08-01-01, SR-2026-08-21-02, FR-2026-09-07-01, TR-2026-09-07-01 |

### Description

This requirement explicitly permits the project to resolve only the
`torch==2.13.0+cpu` distribution from PyTorch's official CPU simple index at
`https://download.pytorch.org/whl/cpu/`. This permission is limited to that
distribution, exact version, and registry. It shall use the generic exception
and verified-installation controls defined by SR-2026-08-21-02.

### Rationale

Argos Translate requires PyTorch through its normal dependency graph. The Linux
PyPI wheel currently includes CUDA packages, while PyTorch's official CPU wheel
preserves Argos support in the CPU OCI image without adding CUDA, cuDNN, or an
NVIDIA driver.

### Notes

The existing seven-day artifact cooldown remains mandatory for every
PyPI-sourced package. The PyTorch CPU index does not expose PyPI-compatible
publication timestamps, so SR-2026-08-21-02's reviewed SHA-256 verification is
the alternative integrity control. The exception authorizes no GPU, CUDA, ROCm,
XPU, or other PyTorch variant. It is intentionally limited to the CPU image's
Linux `x86_64` dependency resolution; other platforms continue to use the
ordinary PyPI source selected by the project's markers.

---

## SR-2026-08-03-02

| Property | Value |
|----------|-------|
| Title | Do not dereference external resources from vector graphics |
| Owner | KrisTC |
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
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-24-04, FR-2026-08-24-03 |

### Description

Google Cloud Translation provider configuration shall be supplied only through the repository-root `.env.local` dotenv file or through the invoking process environment. The `.env.local` file shall remain Git-ignored and shall not be committed. It shall contain `GOOGLE_APPLICATION_CREDENTIALS` with an absolute local path to the service-account credential JSON file and may contain `GOOGLE_CLOUD_PROJECT` or `GOOGLE_CLOUD_TRANSLATION_LOCATION` as explicit overrides. When `GOOGLE_CLOUD_PROJECT` is absent, the provider may read only the mounted or locally referenced service-account JSON file's `project_id` field to select the project.

The provider shall use Google Application Default Credentials from the service-account credential JSON file referenced by `GOOGLE_APPLICATION_CREDENTIALS`. The credential file shall be stored outside the repository or in a Git-ignored location; it shall not be committed, copied into generated artifacts, or written to logs. The provider and setup helper shall not create service accounts or credential files.

The provider shall not implement API-key authentication or read `GOOGLE_API_KEY`. A standard API key is not the supported credential for this provider because it does not identify an IAM principal for the Cloud Translation Advanced v3 API.

The service account shall be granted the Google Cloud Translation API User role (`roles/cloudtranslate.user`) on the configured project. In the Google Cloud role picker, the administrator shall search for and select **Cloud Translation API User**. It shall not select Cloud Translation API Viewer, Editor, or Admin. The provider shall use the credential only for pre-trained `translateText` operations and shall not create or manage Google Cloud resources.

Google documents that Cloud Translation request text is held briefly in memory to provide the service, is not used to train or improve its translation features, and is not made public or shared with third parties. The provider may transmit user-authorized replacement text and its source and target language tags to the configured Cloud Translation endpoint, subject to Google's [Data usage FAQ](https://docs.cloud.google.com/translate/data-usage) and the organization's applicable data-handling obligations.

The Google Cloud Translation provider may process confidential samples when the user requests it, because Google publishes the documented service terms and privacy protections cited above. It shall be excluded from automatic local evaluation. Errors and logs shall not disclose request text, credential values, credential paths, authorization headers, API responses, or Google project identifiers. The interactive successful summary from the local configuration helper may display the configured Google project ID; a project ID is an identifier rather than a credential and is needed only for local operator confirmation.

### Rationale

Cloud translation requires an external trust boundary and credentials. Restricting configuration to the established local environment mechanism prevents accidental version control of secrets. Google's documented API data-use controls permit the provider to process user-authorized text, including confidential samples when the user requests that processing.

### Notes

The project shall provide a unified Google Cloud setup guide with shared credential and configuration instructions and a separate Translation section. It shall direct a developer to obtain a service-account credential JSON file, store the file in an approved local folder outside the repository, and run `uv run --no-sync python scripts/configure_google_cloud_translation.py --credential-file ../credentials/credential.json` to validate the file and configure the provider. The helper shall derive the default project ID from the credential file's `project_id` value. It shall direct the administrator to enable billing and the Cloud Translation API and assign the service account **Cloud Translation API User** (`roles/cloudtranslate.user`) through the project role picker. It shall link to Google's [Cloud Translation setup guide](https://docs.cloud.google.com/translate/docs/setup), [Cloud Translation authentication guide](https://docs.cloud.google.com/translate/docs/authentication), [Cloud Translation access-control guide](https://docs.cloud.google.com/translate/docs/access-control), [Application Default Credentials guide](https://docs.cloud.google.com/docs/authentication/provide-credentials-adc), [Cloud Translation API page](https://console.cloud.google.com/apis/library/translate.googleapis.com), and [Google Cloud billing page](https://console.cloud.google.com/billing). The guide shall not contain a project-specific URL, API key, credential file, access token, or service-account private-key value.

`.env.local` may set `GOOGLE_CLOUD_TRANSLATION_LOCATION` to a supported continental-European location. When it is absent, the provider uses `europe-west1` and Google's EU multi-regional endpoint. The EU endpoint keeps at-rest data and machine-learning processing within continental Europe; it does not remove the developer's responsibility to confirm that their organization approves the configured project, identity, location, and applicable Google Cloud service terms. The endpoint configuration shall follow Google's [Global and multi-regional endpoints documentation](https://docs.cloud.google.com/translate/docs/advanced/endpoints).

Automated tests shall use synthetic configuration values and mocked Google clients. They shall verify that missing or invalid service-account credential configuration fails without secret disclosure, that API-key-only configuration is rejected without a network request, and that the local-evaluation path cannot invoke the remote provider.

---

## SR-2026-08-27-01

| Property | Value |
|----------|-------|
| Title | Secure local persistence of opt-in provider-result caches |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-27-10, FR-2026-08-24-04, SR-2026-08-24-01 |

### Description

The opt-in provider-result cache defined by FR-2026-08-27-10 may persist OCR
text and normalized text-replacement results only in the cache sidecar adjacent
to the source file that established its cache scope. It shall never persist
credentials, credential paths, access tokens, authorization headers, remote API
request or response objects, source/output paths as cache values, or diagnostic
logs.

Cache databases and their contents shall be treated as untrusted local input.
The implementation shall use parameterized SQLite statements, bounded parsing,
and strict normalized-model validation on every cache read. It shall not use
pickle, dynamic code loading, object deserialization, or string interpolation
to execute cache content. A missing, unreadable, locked, malformed, or corrupted
cache shall not expose cached content in an error or log; processing shall
continue with a normal provider call when that is safe to do so.

Cache access shall be explicitly opt-in through `PIPELINE_PLUGIN_CACHE=1` in
the process environment. Its absence or an unrecognized value shall be treated
as disabled. The cache must be Git-ignored, and cache sidecars shall be excluded
from source discovery so they cannot be accidentally treated as documents or
copied to output. The repository's confidential-sample restrictions continue to
apply: confidential cache sidecars and artifacts derived from them remain local,
must not be staged, committed, uploaded, or disclosed.

### Rationale

Source-adjacent caching makes expensive OCR and translation reruns practical,
but it deliberately retains text that may be sensitive. Explicit activation,
safe data-only decoding, conservative error handling, and exclusion from source
processing prevent that local optimization from becoming a new disclosure or
code-execution path.

### Notes

This requirement permits the narrow local persistence exception for Google
translation defined by FR-2026-08-27-10. It does not widen Google Cloud's remote
data boundary, permit another authentication mechanism, or authorize caching
raw Google API responses. Tests shall use synthetic cache data only and verify
that corrupt or malicious-shaped records cannot construct arbitrary objects,
that cache diagnostics contain no request text or secrets, and that source-cache
files are ignored by discovery and Git.

---

## SR-2026-08-29-01

| Property | Value |
|----------|-------|
| Title | Constrain local PDFium rendering of untrusted PDFs |
| Owner | KrisTC |
| Status | Implemented |
| Source | User-approved security review for FR-2026-08-29-01 |
| Date Added | 2026-08-29 |
| Related Requirements | FR-2026-08-29-01, FR-2026-08-29-02, TR-2026-08-29-01, TR-2026-08-29-02, SR-2026-08-01-01 |

### Description

The PDFium renderer introduced for FR-2026-08-29-01 and used by
FR-2026-08-29-02 shall render only bytes
already present in the submitted PDF. It shall not execute JavaScript, launch
links or actions, fetch network resources, open external files, write rendered
pages to disk, or transmit rendered pixels to an external service except
through the user-selected OCR provider's existing approved data boundary.

The adapter shall render at most one page at a time at the approved 200-DPI
resolution. Before allocating the render bitmap, it shall reject a page whose
200-DPI pixel dimensions are non-finite, non-positive, or exceed 50 million
pixels. The failed page shall retain its vector content, and a debug diagnostic
may record only the page number and a stable size-limit reason code.

### Rationale

PDF rendering introduces a native-code parser and potentially large bitmap
allocations for untrusted input. Keeping rendering local, action-free, bounded,
and in memory limits disclosure and resource-exhaustion risk while permitting
OCR of vector-outlined text.

### Notes

`pypdfium2==5.13.0` remains subject to the project's PyPI-only, seven-day
cooldown, wheel-only, and lockfile controls. No registry exception or remote
renderer is authorized by this requirement.

Automated tests shall use synthetic PDFs and mocked renderer boundaries. They
shall verify that an oversized page is retained before renderer invocation and
that diagnostics omit source text, pixels, renderer input, and exception
details.

---

## SR-2026-09-07-01

| Property | Value |
|----------|-------|
| Title | Constrain OCI container mounts, credentials, and plugin trust boundaries |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-07 |
| Related Requirements | SR-2026-08-01-01, SR-2026-08-21-01, SR-2026-08-21-02, SR-2026-08-24-01, SR-2026-08-27-01, FR-2026-09-07-01, FR-2026-09-07-02, TR-2026-09-07-01 |

### Description

Each container image shall treat `/input`, `/plugins`, and `/fonts` as read-only operator-provided mounts, `/output` and `/runtime-cache` as the only normal writable mounts, and the application installation as read-only to its non-root process. Documentation shall instruct operators to mount input, plugins, and fonts read-only. The images shall not copy mounted input, plugin, font, credential, or cache content into their layers.

A provider package under `/plugins` is arbitrary executable code trusted by the operator who mounts it. The project shall not represent a mounted plugin as sandboxed, validate it by executing an installer, or load it from a network location. Plugin-discovery errors shall not expose plugin source contents, environment values, credential paths, source-document paths, or cache paths.

Font files under `/fonts` are also operator-provided input to a native font
parser. The image shall not install them, execute metadata or font-provided
code, fetch related resources, or copy them to another mount. A font parsing or
matching failure shall fall back to the existing Noto source-measurement path
without logging font bytes, credential data, or source-document content.

The image shall not contain credentials, tokens, `.env.local`, confidential sample data, derived confidential artifacts, or provider-result caches. It may read a credential mounted at the fixed secret path of FR-2026-09-07-01 and existing Google configuration environment variables only when the selected provider requires them. It shall not print their values or paths, copy a credential into `/output` or `/runtime-cache`, or set a credential environment variable when an explicit caller-provided value takes precedence. SR-2026-08-24-01's Google Cloud remote-data and least-privilege requirements remain unchanged.

Container startup shall not fetch or install Python packages, resolve dependencies, or download executable plugin code. The one permitted first-use network activity is the existing, explicitly documented runtime-asset bootstrap performed by the container under FR-2026-09-07-01; it shall download only the approved optional Noto assets and PaddleOCR model assets through their existing providers. It shall not process source documents before those downloads complete. Operators may pre-populate and mount `/runtime-cache` when runtime network access is not acceptable.

### Rationale

Container mounts make host data and executable extensions available to the pipeline. Explicit read/write boundaries, non-root execution, and clear credential precedence reduce accidental disclosure while retaining normal provider configuration and model bootstrapping.

### Notes

`/runtime-cache` contains font and model assets only; it is not an authorization for source-adjacent OCR or translation result caching. The established `PIPELINE_PLUGIN_CACHE` opt-in remains disabled by default and is governed by SR-2026-08-27-01.

Automated tests shall use synthetic mounts, configuration, and plugins. They shall verify non-root execution, credential precedence, no credential copying or logging, read-only-mount documentation, no startup dependency installation, and that mounted plugin code is described as trusted rather than sandboxed.

---

## SR-2026-10-21-01

| Property | Value |
|----------|-------|
| Title | Permit explicit read-only aggregate inspection of local provider caches |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-21 |
| Related Requirements | SR-2026-08-27-01, FR-2026-08-27-06, FR-2026-08-27-10, FR-2026-10-21-01 |

### Description

The developer cache-metrics command and an explicitly debug-enabled folder
replacement may read aggregate metadata from an existing cache even when
`PIPELINE_PLUGIN_CACHE=1` is absent. This is an exception only to
SR-2026-08-27-01's opt-in cache-access and per-result validation rules:
inspection shall be read-only, shall not access cached result text, keys, or
provider configuration, and shall not create or modify a cache. Missing or
malformed caches and invalid metadata shall not disclose cache contents or
paths. Provider-result lookups and writes remain opt-in under
SR-2026-08-27-01. Confidential-sample restrictions remain unchanged.

### Rationale

Reading existing metrics is distinct from enabling provider-result caching.

### Verification

Synthetic tests shall verify read-only inspection with caching disabled,
no cache creation or content disclosure, and unchanged cache opt-in behaviour.

---

## SR-2026-10-22-01

| Property | Value |
|----------|-------|
| Title | Keep batched translation within the existing remote-data boundary |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-22 |
| Related Requirements | SR-2026-08-24-01, SR-2026-08-27-01, FR-2026-10-22-02, FR-2026-10-22-03, FR-2026-10-22-06 |

### Description

Batched translation shall not widen the remote-data boundary of SR-2026-08-24-01. The Google Cloud Translation provider shall use only the synchronous `translateText` operation, which requires no Cloud Storage bucket, and shall send only the texts being translated, the source and target language tags, and the configured project and operation parameters. Combining several texts in one request shall not add source paths, document or unit identifiers, part names, metadata, OCR confidence, image bytes, or credentials to what is sent.

Diagnostics, log lines, metrics, progress labels, and the nested-document depth-limit entry added by FR-2026-10-22-02, FR-2026-10-22-03, FR-2026-10-22-05, and FR-2026-10-22-06 shall contain counts, durations, and package part names or depths only, and shall never contain request text, translated text, cache keys, credentials, or project identifiers. Batch composition and quota-wait handling shall not create new persisted data beyond the provider-result cache that SR-2026-08-27-01 already governs, which continues to store only normalized successful per-text results under unchanged keys.

### Rationale

Batching changes how many texts travel in one request, not which data may leave the machine. The synchronous operation avoids a Cloud Storage dependency that would store source text in an additional remote location, and content-free diagnostics keep the added request, retry and progress detail from leaking document content.

### Verification

Synthetic tests with a mocked Google client shall verify that a batched request carries only text and the permitted parameters, that `batchTranslateText` and `translateDocument` are never called, and that logs, diagnostics, and metrics for batches and quota waits contain no text, keys, or credentials.

---

## SR-2026-10-24-01

| Property | Value |
|----------|-------|
| Title | Google Cloud Vision credentials and remote-image boundary |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-24 |
| Related Requirements | FR-2026-10-24-01, FR-2026-10-24-02, SR-2026-08-24-01 |

### Description

The Google Cloud Vision OCR provider shall use the same Google credentials and project configuration as the Google Cloud Translation provider under SR-2026-08-24-01: `GOOGLE_APPLICATION_CREDENTIALS` shall reference the local service-account credential JSON, and `GOOGLE_CLOUD_PROJECT` may override the project ID otherwise derived from that credential file. It shall use `GOOGLE_CLOUD_TRANSLATION_LOCATION` as its location setting. When unset or empty, the effective Vision location shall be the EU multi-region (`eu`), matching the translation provider's default European location. A configured location accepted by the Translation provider's continental-European rule shall select the Vision EU endpoint; any other location shall fail before a network request. This feature shall add no separate Vision credential, project, or location environment variable.

The provider shall authenticate with Google Application Default Credentials from the configured service-account file. It shall not read or support `GOOGLE_API_KEY`. It shall not create credentials, service accounts, projects, IAM bindings, Cloud Storage buckets, or other Google Cloud resources. The configured project shall have the Vision API enabled and billing configured as required by Google. The unified Google Cloud setup guide shall give a separate Vision section with explicit steps to enable the Vision API and grant the runtime service account Service Usage Consumer (`roles/serviceusage.serviceUsageConsumer`) on the configured project for quota and billing consumption, distinguishing that role from the existing Cloud Translation API User role. It shall link to Google's setup and authentication guides and shall not recommend broad project roles or a Cloud Storage role for inline-image annotation.

The provider may transmit a user-authorized source image to the Cloud Vision EU endpoint only when the user selects `google_cloud_vision` for pipeline processing or explicitly selects it with `scripts/ocr_evaluations.py --ocr google_cloud_vision`. It shall not transmit a language hint, file paths, filenames, document metadata, replacement text, OCR confidence, evaluation artifacts, or credentials. It shall use only synchronous online image annotation, which does not require Cloud Storage. It shall not persist the submitted image or raw API response beyond the pipeline's normal in-memory request and response handling.

Google documents that synchronous Vision image data is processed in memory and not persisted to disk, that content is used only to provide the Vision API service and is not used to train or improve its features, and that content is not made public or shared with third parties. Google also documents temporary logging of request metadata such as request time and size. Vision API complies with the Cloud Data Processing Addendum. The provider's EU endpoint shall be used so Google documents that OCR resources are stored and processed only in the European Union. These protections permit user-requested processing of confidential samples subject to the user's organization and applicable data-handling obligations. The documentation shall not describe Google Cloud Vision as unconditionally safe for every confidential document.

The provider shall be excluded from automatic all-provider OCR evaluation and the default OCR contract-test suite. Only the explicit evaluator selection in FR-2026-10-24-02 may send evaluation images to Google. Provider errors, logs, and diagnostics shall not disclose source image content, extracted text, credential values or paths, authorization headers, API response bodies, or project identifiers.

### Rationale

Cloud OCR introduces an external image-processing boundary. Reusing the established Google credential configuration and requiring the EU endpoint makes the data flow and regional processing choice explicit while limiting what the provider sends and records.

### Verification

Automated tests shall use synthetic configuration and a mocked Google client. They shall verify credential and project selection, the unset and configured European location mapping to the EU endpoint, rejection of unsupported locations before network access, use of synchronous image annotation only, the request data boundary, evaluation exclusion, and diagnostics free of image, text, credential, path, API-response, and project-ID values. Tests shall not make network calls or require Google credentials.

### Notes

The relevant Google documentation is the [Cloud Vision API Data Usage FAQ](https://docs.cloud.google.com/vision/docs/data-usage), [Cloud Vision OCR and regional endpoint documentation](https://docs.cloud.google.com/vision/docs/ocr), and [Cloud Vision authentication guide](https://docs.cloud.google.com/vision/docs/authentication). The location setting is shared with Translation, but Vision's API location identifier is the EU multi-region `eu`; Translation's regional location value is mapped to that EU endpoint.

---

## SR-2026-10-28-01

| Property | Value |
|----------|-------|
| Title | Support operator-provided trust for TLS interception |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request following container bootstrap TLS investigation |
| Date Added | 2026-10-28 |
| Related Requirements | FR-2026-08-27-04, FR-2026-09-07-01, SR-2026-08-24-01, SR-2026-09-07-01, TR-2026-10-28-01 |

### Description

Provide a way for an operator to authorize an organisation-specific CA for
container TLS connections when an organisation uses HTTPS interception. The
CA shall be explicitly supplied or selected by the operator; the application
shall not automatically trust a certificate presented by the network.
Certificate chain and hostname verification shall remain enabled.

The connection scope and configuration mechanism are not yet decided. The
owner shall decide whether this applies only to runtime-asset bootstrap or also
to other outbound TLS connections, including translation providers, before
implementation begins. The owner shall also decide how the CA is supplied
and how it interacts with the public trust store and the TLS clients in scope.
This optional capability shall not be required for ordinary public-CA
connections under TR-2026-10-28-01.

### Rationale

An intercepting proxy presents certificates issued by an organisation's CA,
which is not necessarily in a public trust store. Trusting that CA permits the
proxy to inspect traffic within the selected scope; if translation traffic is
included, this can include document text. The operator must understand and
authorize that trust boundary.

### Verification

Once the scope is agreed, automated tests shall use synthetic certificates
and verify that an operator-authorized CA is accepted and an unauthorized CA
is rejected for the TLS clients in scope. Tests shall not disable certificate
or hostname verification or use customer certificates or credentials.

---
