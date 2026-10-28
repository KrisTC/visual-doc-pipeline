# Technical Requirements

---

## Requirement Template

---

## TR-YYYY-MM-DD-NN

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

The checker validates metadata relationships. The verified-installation workflow
remains responsible for selecting the approved artifact and invoking uv to
download and verify its SHA-256 digest before installation.

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

FR-2026-08-24-03 supersedes this requirement's direct `uv run` invocation: each runner shall delegate its Python arguments to the corresponding repository-root `run.ps1` or `run.sh` wrapper. That wrapper remains responsible for executing Python from the project's synchronised uv environment and loading the optional local `.env.local` configuration.

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

## TR-2026-09-07-01

| Property | Value |
|----------|-------|
| Title | Build reproducible Linux CPU and GPU OCI images |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-07 |
| Related Requirements | TR-2026-08-01-01, SR-2026-08-01-01, SR-2026-08-21-01, SR-2026-09-08-01, FR-2026-09-07-01, FR-2026-09-07-02, FR-2026-09-07-03, SR-2026-09-07-01 |

### Description

The repository shall provide Docker build definitions and usage documentation for distinct CPU and GPU Linux `x86_64` OCI images. The root `pyproject.toml` and committed root `uv.lock` shall define their common dependency graph and mutually exclusive `cpu` and `gpu` optional-dependency profiles. The CPU build shall synchronise the locked `cpu` profile; the GPU build shall synchronise the locked `gpu` profile. Each shall install its exact selected locked environment and shall not resolve or upgrade Python dependencies during image startup. Both shall use the same pinned Python version as the project. The CPU image shall install the exact locked PyPI `paddlepaddle` wheel. The GPU image shall select the exact Linux CUDA-enabled PaddlePaddle wheel authorized under SR-2026-08-21-01.

The repository-root `run.sh` and `run.ps1` launchers shall select the `gpu` profile for normal local commands, without introducing a user-facing CPU/GPU launcher option. Its platform markers shall preserve the prior local behaviour: Linux `x86_64` and Windows select CUDA-enabled PaddlePaddle, while macOS and other supported CPU platforms select ordinary PaddlePaddle. A direct `uv` invocation that needs a profile shall select it explicitly. The verified non-default-registry artifact installer shall accept the selected profile and install only approved artifacts reachable from that profile on the current platform. In particular, a CPU image build shall not download or install the CUDA PaddlePaddle artifact from the universal lock.

Every external OCI base image shall be referenced by immutable manifest digest. The build definition shall identify the selected Linux distribution and PaddlePaddle wheel for both images, and the CUDA and cuDNN runtime plus compatibility rationale for the GPU image. The CPU final image shall exclude CUDA, cuDNN, `paddlepaddle-gpu`, and NVIDIA driver components. Each final image shall include only runtime dependencies needed by the pipeline, including Fontconfig configuration and every committed Noto face used by bounded layout or portable output, and shall execute the workload as a non-root user. It shall create the fixed directories required by FR-2026-09-07-01 with ownership and permissions that allow the runtime user to write `/output` and `/runtime-cache` but not the application installation.

The builds shall expose no service port and shall not start a daemon. Their entrypoint shall form the fixed-path folder-replacement invocation specified by FR-2026-09-07-01, append supplied arguments without shell evaluation, and preserve the command's exit status. The CPU build and entrypoint shall not require Docker-in-Docker, host networking, privileged mode, or an NVIDIA device. Each final image shall include the EGL and OpenGL runtime libraries required by the locked `skia-python` wheel. Usage documentation shall make the Linux `x86_64` platform explicit and state that Apple Silicon Docker Desktop runs the CPU image under emulation without NVIDIA GPU support.

A custom-provider image shall be derived from the published base image. Its Docker definition shall install any additional plugin dependencies at build time, pin them in an explicit dependency definition, and subject them to the same wheel-only and provenance controls that apply to project dependencies. It shall not alter the base image's built-in provider packages.

### Rationale

The container must be repeatable enough to debug document-processing output, while GPU runtime compatibility requires explicit version selection. A narrow runtime image and non-root execution reduce the operational surface exposed to untrusted document inputs.

### Notes

The published tags shall distinguish the CPU and GPU variants. The Dockerfile may expose them as named targets, provided the documented build commands select a target explicitly. Native non-`x86_64` variants are out of scope.

Decision recorded 2026-09-08: the CPU image shall use the exact
`torch==2.13.0+cpu` wheel from PyTorch's official CPU index under
SR-2026-09-08-01. Its verified wheel digest and lockfile record shall be
committed before a CPU image is built. This preserves the complete existing
provider set, including Argos Translate, without Linux CUDA artifacts.

The `cpu` and `gpu` profiles are uv optional dependencies rather than
dependency groups because they select mutually exclusive runtime variants. uv
does not select optional dependencies by default; the repository launchers
provide the normal local `gpu` selection and the Docker build selects its
profile explicitly.

Automated build checks shall verify lockfile use, digest-pinned bases, final user, entrypoint argument formation, fixed-directory permissions, and absence of runtime package installation. They shall not download model assets, require credentials, or require a GPU.

---

## TR-2026-09-10-01

| Property | Value |
|----------|-------|
| Title | Validate pull requests with GitHub Actions continuous integration |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-10 |
| Related Requirements | TR-2026-08-01-01, TR-2026-08-01-03, TR-2026-08-01-04, TR-2026-09-07-01, SR-2026-08-01-01, SR-2026-08-21-02, SR-2026-09-08-01, FR-2026-08-27-04 |

### Description

The repository shall provide `.github/workflows/ci.yml`.  GitHub Actions shall
run its CI checks for every pull-request revision, including revisions pushed
after the pull request is opened or reopened.  The workflow shall test the
pull request's merge result against its target branch, so a passing result
represents the code that would be merged.

The workflow shall use a Linux `x86_64` GitHub-hosted runner and the exact
Python version declared by the project.  It shall perform the following
checks, failing the workflow when any check fails:

1. Run `scripts/check-dependency-policy.py` before dependencies are
   installed.
2. Create the development environment from the committed lockfile using the
   repository's verified dependency-installation workflow with the `cpu`
   profile.  The CI dependency installation shall not resolve, upgrade, or
   lock dependencies.
3. Run `scripts/typecheck-python.py`.
4. Download the optional portable fonts with
   `scripts/bootstrap_runtime_assets.py --fonts-only`, so the tests run against
   the same Noto Sans Math and Noto Sans Symbols 2 faces that fitted layout
   requires at runtime (FR-2026-08-27-04).
5. Run the complete automated test suite through `scripts/run-tests.sh`.
6. Build both named OCI image targets, `cpu` and `gpu`, from the repository
   `Dockerfile` for `linux/amd64`.  The workflow shall not run either image,
   download PaddleOCR or other OCR model assets, require credentials, or require a GPU.

The workflow shall run with the minimum GitHub token permissions needed to
read the repository and shall not receive repository secrets, deployment
credentials, or Google Cloud credentials.  It shall use the `pull_request`
event rather than an event that executes pull-request code with target-branch
privileges.  Third-party GitHub Actions used by the workflow shall be pinned
to immutable commit revisions.

The CI workflow shall publish distinct, stable check names for the dependency
policy, Python verification, and OCI build checks.  A repository administrator
shall configure the target branch's GitHub protection or ruleset to require
those successful checks before merge.  The repository workflow itself shall
not grant, remove, or substitute for a human pull-request review approval.

### Rationale

Pull-request CI gives contributors and reviewers repeatable evidence that a
change preserves the dependency controls, Python quality gates, test suite,
and both distributable container definitions before it is merged.  Keeping
untrusted pull-request code in a read-only, secret-free workflow limits the
effect of contributions from forks.  Downloading the verified optional fonts
before the tests keeps the fitted-layout fallback path under test; without them
the fallback is silently skipped on the runner and tests pass without exercising it.

### Notes

The `cpu` profile is selected for Python verification because the GitHub-hosted
runner has no NVIDIA GPU.  Building the GPU image validates its Dockerfile and
locked dependency profile without asserting GPU runtime behaviour; GPU runtime
validation remains a separate capability.

GitHub branch-protection configuration is repository-hosted state rather than
versioned content in `ci.yml`.  Its required-check names must match the
workflow's published check names.  This requirement does not yet define
release publishing, package publication, image registry choice, tag policy,
or release credentials; those need separate requirements before a publishing
workflow is implemented.

---

## TR-2026-09-10-02

| Property | Value |
|----------|-------|
| Title | Publish version-tagged CPU and GPU OCI images to GitHub Container Registry |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-10 |
| Related Requirements | TR-2026-09-07-01, TR-2026-09-10-01, SR-2026-09-07-01 |

### Description

When a Git tag matching `v*` is created, GitHub Actions shall publish a release
only when the tag resolves to the current tip commit of `main`. The workflow
shall build the repository's `cpu` and `gpu` Dockerfile targets for Linux
`amd64` and publish them to, respectively,
`ghcr.io/<repository-owner>/visual-doc-pipeline-cpu` and
`ghcr.io/<repository-owner>/visual-doc-pipeline-gpu`. Each image shall be
published with the Git tag itself as its version tag and with `latest`, which
shall identify that same release.

The workflow shall create a GitHub Release for the Git tag after both variant
images have been published successfully. It shall not create the GitHub
Release when either image build or publication fails.

The workflow shall use GitHub Actions' scoped `GITHUB_TOKEN` with the minimum
permissions needed to read repository contents, write packages, and create
the GitHub Release. It shall not receive repository secrets or deploy
credentials. It shall use only third-party GitHub Actions pinned to immutable
commit revisions.

The workflow shall not create, alter, or delete Git tags. It shall permit
rerunning a failed release workflow for the same tag. The repository owner
shall protect release tags through GitHub repository settings if immutability
is required.

### Notes

The exact image owner is derived from the repository owner at workflow runtime.
This permits the same workflow to operate after a repository transfer without
embedding an account name in version-controlled configuration.

Requiring the current `main` tip is the initial release policy. A future
maintenance-release policy can deliberately permit version tags on selected
release branches or older commits after its branch and support rules are
defined.

OCI registry publication across the two image repositories is non-transactional.
If one push fails after the other succeeds, the workflow shall leave the
partial registry state, create no GitHub Release, and fail. Rerunning the
workflow for the same tag shall republish both variants, converge their
version and `latest` tags, and then create the release.

---

## TR-2026-09-11-01

| Property | Value |
|----------|-------|
| Title | Annotate published OCI images with standard project and release metadata |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request; [GitHub Container Registry image-labelling guidance](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#labelling-container-images) |
| Date Added | 2026-09-11 |
| Related Requirements | TR-2026-09-07-01, TR-2026-09-10-02 |

### Description

The release workflow defined by TR-2026-09-10-02 shall apply OCI image
annotations to each published CPU and GPU image. The annotations shall be
present in the final image configuration for both the version and `latest`
tags, and shall use the `org.opencontainers.image.*` label keys.

Each published image shall include the following accurate metadata:

- `org.opencontainers.image.title`: `visual-doc-pipeline`.
- `org.opencontainers.image.description`: the project's published short
  description, without claiming capabilities that the image does not provide.
- `org.opencontainers.image.source` and `org.opencontainers.image.url`: the
  canonical HTTPS URL of the repository that produced the image,
  `https://github.com/<repository-owner>/<repository-name>`.
- `org.opencontainers.image.licenses`: the SPDX identifier `Apache-2.0`.
- `org.opencontainers.image.version`: the release Git tag.
- `org.opencontainers.image.revision`: the immutable commit SHA resolved by
  that release tag.
- `org.opencontainers.image.variant`: `cpu` for the CPU image and `gpu` for
  the GPU image.

The workflow shall derive repository, tag, and commit values from its GitHub
Actions release context or checked-out release commit. It shall not hard-code
the repository owner, use an untrusted tag value as a shell expression, or
include credentials, environment values, input-document data, or other
sensitive data in image metadata. A failed metadata derivation or failed image
publication shall fail the release before its GitHub Release is created.

Automated release-workflow verification shall verify every required annotation
for both image variants, including the CPU/GPU distinction and the workflow's
derivation of version, revision, and repository URL from the release context.

### Rationale

Standard OCI annotations make both GitHub Container Registry packages
recognisable and traceable to their source repository and exact release commit,
while giving operators an unambiguous CPU or GPU variant indicator.

### Notes

`org.opencontainers.image.source` is the annotation GitHub Container Registry
uses to associate an image package with its source repository. The requirement
does not add a build-time timestamp annotation because an uncontrolled current
time would undermine the reproducibility objective of TR-2026-09-07-01.

---

## TR-2026-09-11-02

| Property | Value |
|----------|-------|
| Title | Include versioned container-image references in GitHub Release notes |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-11 |
| Related Requirements | TR-2026-09-10-02 |

### Description

After it has successfully published both images required by TR-2026-09-10-02,
the release workflow shall create or update the corresponding GitHub Release
with a `## Container images` section. That section shall contain separately
labelled, copyable CPU and GPU image references using the release Git tag:

- CPU: `ghcr.io/<repository-owner>/visual-doc-pipeline-cpu:<release-tag>`.
- GPU: `ghcr.io/<repository-owner>/visual-doc-pipeline-gpu:<release-tag>`.

The image owner shall use the same lowercase repository-owner derivation as
the published image tags. The workflow shall derive both references from its
release context; it shall not hard-code a repository owner or substitute the
mutable `latest` tag.

On a rerun for a release that already exists, the workflow shall ensure this
section is present and accurate rather than leaving an empty or stale release
body. The section may coexist with release notes from other sources, which
the workflow shall preserve.

Automated release-workflow verification shall confirm that the generated
release notes contain both variant labels and their version-tagged image
references, and that rerun handling updates the container-images section.

### Rationale

Operators need a stable, copyable image reference at the release point. A
version tag identifies the released artifact, whereas `latest` can later refer
to a different release.

---

## TR-2026-09-11-03

| Property | Value |
|----------|-------|
| Title | Generate a requirements-based changelog draft for a proposed release |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-11 |
| Related Requirements | TR-2026-09-10-02 |

### Description

The project shall provide a repository-root script that determines the next
release version and generates, without modifying `CHANGELOG.md`, a Markdown
changelog draft at `outputs/changelog-drafts/<version>.md`. The
`outputs/changelog-drafts/` directory shall be ignored by Git. The script
shall overwrite an existing draft or requirements-diff artifact for that
version if it already exists. On successful completion, it shall print the
proposed release tag in the form `v<major>.<minor>.<patch>` and the two
generated artifact paths relative to the repository root.

Immediately after the draft's H1 heading, the script shall write a copy-ready
release H2 heading containing the proposed version and the local calendar date
on which the script runs, formatted as `YYYY-MM-DD`. When a version-baseline
tag exists, the version text shall link to GitHub's comparison page from that
tag to the proposed `v<version>` tag. The script shall derive the GitHub
repository URL from the `origin` remote; it shall fail if `origin` is not a
recognised GitHub repository URL. When no version-baseline tag exists, the
heading shall contain the unlinked version and date because no comparison is
available.

The script shall inspect release tags matching `v<major>.<minor>.<patch>` and
select the highest valid semantic-version tag as its version baseline. With no
arguments, it shall increment that baseline's minor version and reset its
patch version to zero. If invoked with the optional argument `major`, it shall
increment the major version and reset its minor and patch versions to zero. If
no matching release tag exists, it shall use `0.1.0`. It shall reject every
other argument.

The script shall collect changes to every file directly in `requirements/`
from the version-baseline tag through `HEAD`, and shall write the complete Git
diff for those files to
`outputs/changelog-drafts/<version>.requirements.diff`. If no matching release
tag exists, or `CHANGELOG.md` is empty, the script shall treat the release as
the first release: it shall write the complete requirements history diff
through `HEAD` and include every requirement currently present in
`requirements/` in the draft. A missing `CHANGELOG.md` shall be treated as an
empty changelog.

From the requirements diff, the script shall identify the distinct
requirements that were added, updated, or deleted. The generated draft shall
group those requirements by their source file in `requirements/`. For each
group, it shall derive a human-readable title and scope description from the
corresponding routing-table entry in `requirements/README.md`. Within each
file group, it shall separate added, updated, and deleted requirements and
provide a table for each non-empty change-kind section with ID, title, status,
and owner columns. For added and updated requirements, these fields shall be
taken from the requirement at `HEAD`; for deleted requirements, they shall be
taken from its last version before deletion.

The draft shall order its source-file groups as follows when those groups have
identified requirements: security requirements first, technical requirements
second, general requirements third, and text-replacement requirements fourth.
It shall order every other group alphabetically by requirements filename after
those four groups.

The copy-ready release H2 heading shall be the parent heading for all generated
content. Source-file summary groups and the Requirement details section shall
use H3 headings; their nested headings shall use successively lower heading
levels.

After the tables, the generated draft shall contain a separate headed section
for each source requirements file using the same human-readable title and
scope description. Each section shall contain one entry for every identified
requirement from that file. An entry heading shall include only its ID, title,
and status, with the status in brackets after the title, followed by that
requirement's Rationale section. A deleted requirement's entry shall use its
last version before deletion. The script shall preserve the requirement text
in the generated draft sufficiently to distinguish its Rationale from other
sections, but shall not add requirement fields other than those specified.

### Rationale

Release notes need a reviewable summary of the requirements that changed since
the preceding release, while retaining the complete source diff for audit and
without allowing a preparation tool to alter the published changelog.
This will produce input to the developer or coding agent to produce the
actual changelog entry in `CHANGELOG.md`.

### Notes

The release workflow currently uses Git tags matching `v*`
(TR-2026-09-10-02); this requirement narrows the script's supported release
tags to semantic-version tags. When valid release tags exist but
`CHANGELOG.md` is empty, the tags determine the next version but the draft
still includes all current requirements and the complete requirements history
diff, as required for an initial changelog entry.

---

## TR-2026-09-12-01

| Property | Value |
|----------|-------|
| Title | Publish the matching changelog entry in GitHub Release notes |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-12 |
| Related Requirements | TR-2026-09-10-02, TR-2026-09-11-02, TR-2026-09-11-03 |

### Description

Before authenticating to a registry or building or publishing either image,
the release workflow shall read the checked-out `CHANGELOG.md` and validate
that it contains an entry for the release tag's semantic version after its
leading `v` is removed. A release entry is an H2 heading whose version is
either literal text or the visible text of a Markdown link. In both forms the
version shall exactly equal the tag's version; any date or other text after
the version is permitted. This shall support the linked version headings
generated under TR-2026-09-11-03.

The workflow shall fail before the image build or publication steps when
`CHANGELOG.md` is missing, cannot be read, or has no matching release entry.

After both images have been published successfully, the workflow shall create
or update the GitHub Release with the complete matching changelog entry: its
H2 heading and every following line, including headings of every lower level,
up to but excluding the next release-entry H2 heading or the end of the file.
The release notes shall retain the `## Container images` section required by
TR-2026-09-11-02.

On a workflow rerun, the workflow shall replace its previously generated
changelog-entry content and container-images section with the current,
validated content while preserving release-note content managed by other
sources. It shall use unambiguous machine-readable boundaries for the
workflow-managed changelog content, rather than relying on user-authored
headings to identify the prior content.

Automated release-workflow verification shall cover literal and linked version
headings, complete extraction through nested headings, stopping at the next
release-entry heading and at end of file, fail-fast behaviour before any image
build or publication, and idempotent rerun handling.

### Rationale

The changelog is the reviewed release summary. Validating its entry before
costly, irreversible image publication prevents published artifacts without
corresponding release notes, while bounded extraction keeps adjacent release
entries out of the published release page.

---

## TR-2026-10-27-01

| Property | Value |
|----------|-------|
| Title | Command-line argument tests run in process |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request to reduce unit-test iteration time |
| Date Added | 2026-10-27 |
| Related Requirements | TR-2026-08-01-03, FR-2026-08-01-01, FR-2026-08-03-03, FR-2026-08-04-03, FR-2026-08-22-01 |

### Description

An automated test that verifies command-line parsing, validation, `--help` content, or the exit code and message of an anticipated argument error shall call the script's entry point or argument parser in the test process, with a synthetic `argv` and captured standard streams. It shall not start a Python subprocess for each case.

The test suite shall keep exactly one subprocess test per user-invokable script that proves the script runs as a direct script (`python scripts/<name>.py --help` exits 0 and prints usage). That test verifies the launch path, including import resolution when run as a script, and shall not repeat assertions about option content, which the in-process tests verify.

Moving a case in process shall not weaken its assertions: it shall still verify the exit status, that the error message is reported on standard error as an argparse usage error without a traceback, and the exact message text it verified before.

### Rationale

Each subprocess re-imports the full folder-replacement pipeline (about 1.8 s per start, measured on the development machine), so one test with several argument-error cases cost over 13 s. Argument handling is Python logic that does not need a new interpreter; only the direct-script launch path does.

### Verification

The tests covering FR-2026-08-04-03 and the help-content assertions of FR-2026-08-03-03 shall use no subprocess. The tests for FR-2026-08-01-01, FR-2026-08-03-03 and FR-2026-08-22-01 keep their single direct-script subprocess check.

---

## TR-2026-10-27-02

| Property | Value |
|----------|-------|
| Title | Parallel test execution by default |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request to reduce unit-test iteration time |
| Date Added | 2026-10-27 |
| Related Requirements | TR-2026-08-01-01, TR-2026-08-01-03, TR-2026-09-10-01, TR-2026-10-27-03, SR-2026-08-01-01, SR-2026-08-21-02, FR-2026-08-01-02 |

### Description

The test runners `scripts/run-tests.sh` and `scripts/run-tests.ps1` shall run the complete test suite in parallel by default. They shall use `pytest` with `pytest-xdist` to run the existing `unittest.TestCase` tests in `tests/`, discovering the files matching `test_*.py`. `pytest` and `pytest-xdist` shall be declared as development dependencies in the `dev` dependency group of `pyproject.toml` and locked in `uv.lock`. Both dependencies are subject to SR-2026-08-01-01 and SR-2026-08-21-02 and shall be installable by the CI dependency-installation workflow of TR-2026-09-10-01.

This requirement supersedes the `unittest`-discovery mechanism of TR-2026-08-01-03 for the default run. Everything else in TR-2026-08-01-03 remains: the tests live in `tests/`, both platform runners exist and run the same command, they delegate to the `run.ps1` or `run.sh` wrapper (FR-2026-08-24-03), and they return the underlying exit code.

The runners shall also provide a `--serial` option that runs the suite in one process with standard-library `unittest` discovery of `tests/` with the pattern `test_*.py`, exactly as TR-2026-08-01-03 specified. Serial mode is the reference execution mode, for reproducing a failure that may depend on parallel execution.

Parallel mode shall:

- discover the same set of tests as serial mode
- distribute tests across worker processes, defaulting to `max(1, N - 2)` workers where `N` is the number of available CPU cores, so two cores remain free for the developer's other work, and accept an override for the worker count; when the result is one worker, run the tests in the main process without starting a worker
- report a failure or error in any test or subtest, including a failure inside a `subTest`, as a non-zero exit code
- keep skipped tests and subtests visible with their skip reason, including provider-declared skips required by FR-2026-08-01-02
The CI workflow of TR-2026-09-10-01 shall run the complete suite with `--serial`. CI is the authoritative check and its hosted runners have few cores, so parallel execution would add little speed; running the reference mode there keeps its result independent of worker scheduling. Local parallel runs still reveal any test-order or shared-state dependence.

Tests shall be independent of execution order and of each other: each test shall use its own temporary directories and shall not write to a shared repository path, `outputs/`, or the user's `.env.local`. A test that cannot meet this shall be identified and run serially or fixed.

### Rationale

The test suite is dominated by independent, CPU-bound document and image processing. Parallel execution by default reduces wall time on multi-core machines without changing the tests, which is the purpose of a fast edit-test loop. A serial mode remains available so that a failure can be reproduced without concurrency as a factor.

### Verification

A verification run shall show that the passed, failed, and skipped counts reported by parallel mode equal those of serial mode for the complete suite. A deliberately failing subtest in a temporary test module shall demonstrate that parallel mode exits non-zero.

### Notes

Assumptions for owner review: the Paddle OCR contract test loads a model in whichever worker runs it, and several workers may load PaddleOCR models concurrently, so memory and GPU use may rise; the implementation shall measure this and, if necessary, propose limiting that test to one worker. If subtest failures or provider-declared subtest skips are not reported correctly by the pinned `pytest` version, the implementation shall select a `pytest` version or plugin that reports them, or stop and ask for direction rather than weakening the checks above.

---

## TR-2026-10-27-03

| Property | Value |
|----------|-------|
| Title | Test runners forward arguments and support a fast subset |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request to reduce unit-test iteration time |
| Date Added | 2026-10-27 |
| Related Requirements | TR-2026-08-01-03, TR-2026-09-10-01, TR-2026-10-27-02, FR-2026-08-01-02 |

### Description

`scripts/run-tests.sh` and `scripts/run-tests.ps1` shall forward every command-line argument they do not themselves define to the underlying test command, so a developer can select tests (such as by name pattern or module) and request standard test-runner options (such as verbose output or `--durations`) without bypassing the runners. With no arguments the runners shall run the complete suite as TR-2026-10-27-02 specifies, and they shall exit with the underlying test-process exit code. Forwarded arguments go to the active underlying runner: `pytest` by default and `unittest` with `--serial`. The two runners shall accept the same options with equivalent behaviour on their platforms, and their usage shall be documented in `docs/development.md`.

The runners shall define a `--fast` option that omits tests marked as slow. A plain run, with no `--fast`, includes them. The project shall provide a single decorator in the shared test-support code that marks a test as slow. When `--fast` is set, the runner shall signal it to the test process through an environment variable, and the decorator shall skip the marked test with a reason that identifies it as slow and names `--fast`. The skip shall use the standard skip mechanism, so the run output reports the number of skipped tests. When `--fast` is not set, a marked test shall run unchanged.

The decorator shall be applied to the OCR provider contract test of FR-2026-08-01-02. It may also be applied to any other test that takes longer than 5 seconds in a serial reference run, provided a faster test covers the same requirement behaviour with synthetic data. It shall not be applied to a test that is the only test of a requirement.

A fast run is for iteration only. The development guidance in `docs/development.md` and any task that requires a passing test suite shall treat a complete run as the completion check, and CI (TR-2026-09-10-01) shall run the complete suite without `--fast`. A skip declared by an OCR provider for a specific case (FR-2026-08-01-02) is unaffected by this option.

### Rationale

The runners currently cannot pass `--durations`, `-k`, or similar options, so a developer must call the wrapper by hand to profile or filter. A deliberately skip-visible fast subset shortens the edit-test loop without silently reducing what the suite verifies for a merge.

### Notes

Today no test-specific environment variable exists; the runners only pass the optional `.env.local` file through `run.ps1` or `run.sh`. This requirement adds one, set by the runner for the test process when `--fast` is given and read only by the slow-test decorator. Its name will be chosen at implementation. Because `unittest` and `pytest` accept different options, `docs/development.md` lists the options for each runner. `--fast` combines with both parallel and `--serial` modes.

---

## TR-2026-10-28-01

| Property | Value |
|----------|-------|
| Title | Provide public CA trust in CPU and GPU container images |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request following container bootstrap TLS failure |
| Date Added | 2026-10-28 |
| Related Requirements | FR-2026-08-27-04, FR-2026-09-07-01, TR-2026-09-07-01, TR-2026-09-10-01, SR-2026-09-07-01, SR-2026-10-28-01 |

### Description

Both the CPU and GPU final container images shall include a public CA trust
store usable by the image's Python standard-library HTTPS client with its
default configuration and non-root runtime user. An operator shall not need
to mount a CA bundle or configure certificate environment variables for
connections to the approved runtime-asset sources when their certificates
chain to a publicly trusted CA.

Runtime-asset downloads, including HTTPS redirects, shall retain certificate
chain and hostname verification. This requirement does not change the pinned
Noto archive digests, PaddleOCR's model-download behaviour, or the container
startup restrictions in SR-2026-09-07-01. Support for an organisation-specific
interception CA is a separate proposal in SR-2026-10-28-01.

### Rationale

The GPU image's Python runtime was observed to have no usable default CA
trust store, causing first-use font downloads to fail before processing.
Supplying public trust roots to both variants makes the documented bootstrap
usable without an operator-provided CA on ordinary public-CA networks.

### Verification

Automated checks shall cover the CA-trust configuration of both image targets.
An image-level network smoke check shall exercise the actual Python runtime in
each final image as the non-root user, without a host CA mount or certificate
environment override. It shall verify HTTPS certificate and hostname
validation for both pinned Noto download URLs, including their redirects.
The check shall not require a GPU, customer documents, or credentials, and
shall report network or TLS failures rather than treating them as success.

The image-level smoke check is separate from the pull-request CI workflow:
TR-2026-09-10-01 currently prohibits running either image in that workflow.

---