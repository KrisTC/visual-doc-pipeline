# Google Cloud Translation Requirements

Google Cloud Translation provider behaviour and local configuration. Related credential and remote-data controls remain in `security-requirements.md`.

## FR-2026-08-24-04

| Property | Value |
|----------|-------|
| Title | Translate text and filenames with Google Cloud Translation |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-02-06, FR-2026-08-03-01, FR-2026-08-03-04, FR-2026-08-24-03, SR-2026-08-24-01 |

### Description

The default text-replacement provider factory shall discover a `google_cloud_translate` provider. The provider shall use the Google Cloud Translation Advanced v3 API to translate ordinary text from the request's source BCP 47 language tag to its target BCP 47 language tag.

For filename requests, the provider shall translate the filename stem while retaining the original suffix unchanged. It shall reject an empty translated stem or a translated stem containing a path separator, NUL character, `.` or `..`, by raising `TextReplacementProviderError`. The existing folder-replacement collision and output-root safety checks shall continue to apply.

The provider shall return `TextReplacementProviderError` when required local configuration is absent, authentication fails, the requested language pair is rejected, the Google API call fails, or the API response does not contain a translation. It shall not fall back to another cloud service or to `argos_translate`.

### Rationale

Argos Translate provides an offline option, but its translation quality is insufficient for some document-replacement workloads. Google Cloud Translation provides a separately selectable managed translation service without changing the shared replacement API or requiring the local provider to be removed.

### Notes

The provider shall use the Google Cloud Translation Advanced v3 API's documented source- and target-language fields. It shall pass the request's BCP 47 tags unchanged unless the Google API requires a documented normalization. A non-empty `GOOGLE_CLOUD_PROJECT` shall select the Google Cloud project. When that variable is absent or empty, the provider shall derive the project from the validated service-account credential JSON file's non-empty `project_id` value. It shall fail before making a network request when neither source yields a project ID. An explicitly supplied environment project shall take precedence over the credential value.

The provider shall use `europe-west1` and the `translate-eu.googleapis.com` multi-regional endpoint when `GOOGLE_CLOUD_TRANSLATION_LOCATION` is absent or empty. When that setting names a Cloud Translation-supported location within continental Europe, it shall select the same EU endpoint and use that location in its API resource names. A non-European location value shall raise `TextReplacementProviderError`; this feature does not support the global or US endpoints. This feature shall use Google's pre-trained NMT model and shall not support custom AutoML models. The endpoint behavior and regional restrictions shall follow Google's [Global and multi-regional endpoints documentation](https://docs.cloud.google.com/translate/docs/advanced/endpoints).

Google Cloud credential configuration shall comply with SR-2026-08-24-01. A successful result shall use confidence `0.0`, because the API does not return a calibrated translation-confidence value for this operation. Empty input and requests whose source and target language tags are equal after case-insensitive comparison shall return the input unchanged with confidence `0.0` and shall not call the API.

The provider shall require the service-account Application Default Credentials configuration defined by SR-2026-08-24-01. Missing `GOOGLE_APPLICATION_CREDENTIALS`, an unreadable credential file, a credential without a usable project ID when no environment-project override exists, or an API-key-only configuration shall raise `TextReplacementProviderError` before making a network request.

`google_cloud_translate` shall declare `LOCAL_EVALUATION_ELIGIBLE = False`. Automated local text-replacement evaluation and its default test suite shall not instantiate it or send evaluation text to Google. This evaluation exclusion does not prevent user-requested processing of confidential samples through the provider when it complies with SR-2026-08-24-01.

The provider shall send to Google only the replacement request's text and source and target language tags, plus the configured project and API operation parameters. It shall not send source paths, output paths, document metadata, OCR confidence, image bytes, evaluation artifacts, or credentials. It shall not persist translation text or API responses beyond the normal in-memory replacement result.

Provider-owned automated tests shall use synthetic text and filenames only. They shall mock the Google client and verify credential-project derivation, explicit-project precedence, the default and overridden EU location, filename safety, unchanged same-language and empty requests, configuration and API failures, API request construction, and that no confidential or credential value appears in errors or logs. Tests shall not make network calls or require Google credentials.

---

## FR-2026-08-24-05

| Property | Value |
|----------|-------|
| Title | Configure and verify Google Cloud Translation credentials |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-24-03, FR-2026-08-24-04, SR-2026-08-24-01 |

### Description

The project shall provide `scripts/configure_google_cloud_translation.py` to configure and verify the local Google Cloud Translation provider. The Python helper shall be invoked through the project's locked Python environment, for example `uv run --no-sync python scripts/configure_google_cloud_translation.py --credential-file ../credentials/credential.json`. It shall accept `--credential-file` with an absolute or relative path to a service-account credential JSON file and optional `--location`. The helper shall resolve a relative credential-file path against the invoking process's current working directory before validation, probing, and writing its absolute forward-slash form to `.env.local`. It shall derive the project ID from the credential file's `project_id` value. The optional location shall follow FR-2026-08-24-04: an unset location selects `europe-west1` and a supported European location selects the EU endpoint. Its command help shall state that omission selects `europe-west1` (Belgium) and list `europe-west3` (Frankfurt) and `europe-west4` (Netherlands) as further examples rather than an exhaustive availability list.

Before updating `.env.local`, the helper shall validate that the supplied path is an existing service-account credential JSON file, then perform one synthetic `translateText` request through the Google Cloud Translation provider using a fixed repository-owned test string. The probe shall confirm that the credentials, project, selected endpoint, and location work together. It shall not use sample data, document content, OCR output, user-provided text, or confidential data.

After a successful probe, the helper shall atomically create or update only its marked `GOOGLE_APPLICATION_CREDENTIALS` and optional non-default `GOOGLE_CLOUD_TRANSLATION_LOCATION` entries in the repository-root `.env.local` file. It shall not write `GOOGLE_CLOUD_PROJECT`, because the provider derives that value from the credential file unless an operator deliberately supplies an explicit override. It shall write `GOOGLE_APPLICATION_CREDENTIALS` as a double-quoted absolute path with forward slashes, so the uv dotenv loader can parse a Windows credential-file path. It shall preserve all user-managed entries, including the CUDA `PATH` entry managed by `scripts/configure-paddle-cuda-environment.ps1`. If validation or the probe fails, it shall leave an existing `.env.local` unchanged and shall not create one that did not already exist.

### Rationale

Service-account key creation may be restricted, while an approved local credential file can be distributed for a single-machine utility. A project-owned setup command makes that credential configuration explicit, validates it before use, and avoids hand-editing provider settings into an ignored environment file.

### Notes

The helper shall print the credential file's basename, project ID, selected endpoint, selected location, and a success or concise failure category. A Google Cloud project ID is an identifier rather than a credential; it is permitted in the successful, interactive local summary but shall not be included in failure diagnostics or logs. The helper shall not print the credential file's contents, absolute credential path, private-key fields, access tokens, authorization headers, or the probe's source or translated text.

The helper shall replace its prior marked block atomically and preserve all user-managed dotenv entries. It shall recognise the previous PowerShell helper's marker during this migration, replace that block with the Python helper's marker, and shall not remove similarly named unmarked entries.

The helper shall not create a Google Cloud project, enable billing or APIs, create service accounts, create credential files, modify IAM roles, or make persistent Google Cloud configuration changes. The setup guide required by SR-2026-08-24-01 shall direct the developer to obtain the credential file from the appropriate project administrator before running the helper.

Automated tests shall use temporary synthetic credential files and a mocked Google client. They shall verify managed dotenv-entry creation and replacement, preservation of arbitrary user-managed dotenv entries, preservation of the CUDA script's managed `PATH` entry, probe failure rollback, API-key-shaped input rejection, and that diagnostics contain no credential value or probe text.

---

## FR-2026-08-28-01

| Property | Value |
|----------|-------|
| Title | Reuse Google Cloud Translation client within a provider instance |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PDF native-text performance diagnosis |
| Date Added | 2026-08-28 |
| Related Requirements | FR-2026-08-24-04, SR-2026-08-24-01, FR-2026-08-27-10 |

### Description

`GoogleCloudTranslateProvider` shall lazily load and validate its local Google
configuration, then create one `TranslationServiceClient` for its selected
endpoint. It shall reuse that configuration and client for every subsequent
non-empty, cross-language replacement request made through the same provider
instance. Empty and case-insensitively same-language requests shall continue to
return without loading configuration or creating a client.

The provider factory's existing fresh-provider-per-`create()` contract remains
unchanged. Therefore a new factory-created provider shall reread the local
environment and credential-file configuration, while a provider already in use
shall retain the configuration selected at its first remote request. A failed
configuration validation or client construction shall not be retained: a later
request may retry initialization. A `translateText` operation failure shall
retain the initialized client and continue to raise the existing normalized
provider error; it shall not silently select another endpoint or provider.

This requirement shall not batch requests, alter individual `translateText`
request construction, persist configuration or client state, widen the remote
data boundary, or expose configuration values in errors or logs. FR-2026-10-22-02
supersedes only the prohibition on batching requests.

### Rationale

PDF native text can produce many small replacement calls. Re-reading the local
credential JSON and constructing a Google client for every one adds unnecessary
local work and connection setup around every remote operation. Reuse preserves
the existing request semantics and trust boundary while removing that repeated
per-call setup cost.

### Notes

Automated tests shall use synthetic configuration and mocked clients. They shall
verify one configuration validation and one client construction for multiple
ordinary replacement calls, no initialization for empty or same-language calls,
fresh configuration for a new provider instance, initialization retry after a
construction failure, and unchanged endpoint, error-sanitization, and request
contents behaviour.

---

## FR-2026-09-03-04

| Property | Value |
|----------|-------|
| Title | Bound and diagnose transient Google Cloud Translation request waits |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following stalled embedded-workbook translation |
| Date Added | 2026-09-03 |
| Related Requirements | FR-2026-08-24-04, FR-2026-08-28-01, SR-2026-08-24-01, FR-2026-08-28-03 |

### Description

For each non-empty cross-language `translateText` operation, the Google Cloud
Translation provider shall apply a 10-second RPC deadline. It shall make at
most three total attempts: the initial attempt and at most two retries. A retry
is permitted only after a deadline expiry or another transient transport
failure; invalid requests, authentication and authorization failures, and other
non-transient API failures shall fail immediately. The provider shall retain
its initialized client across attempts.

After the final unsuccessful attempt, the provider shall raise the existing
normalized `TextReplacementProviderError`, so the folder processor's existing
per-source failure isolation applies. Its safe failure diagnostic shall include
the provider name, failure category, attempted-call count, per-attempt deadline
seconds, total configured attempt limit, input character count, source and
target language tags, and filename flag. It shall not include request text,
translated text, source or output paths as values, credentials, project IDs,
authorization headers, API response bodies, or chained provider messages.

### Rationale

An RPC without a deadline can block a document pipeline indefinitely. A small,
bounded retry window tolerates transient transport failures while ensuring a
single replacement request cannot silently stall an entire source document.

### Notes

Automated tests shall use mocked clients and synthetic inputs. They shall verify
the 10-second deadline for each attempt, success after a transient failure,
termination after three attempts, immediate non-transient failure, unchanged
client reuse, and complete safe diagnostic metadata without request text or
credentials.

FR-2026-10-22-03 supersedes this requirement's 10-second deadline value and
its per-operation wording, which becomes per `translateText` request. The
three-attempt limit and the transient-failure rules remain in force.

---

## FR-2026-10-22-02

| Property | Value |
|----------|-------|
| Title | Translate a batch of texts in one Google Cloud Translation request |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request: batch text replacement (`docs/batch-text-replacement-plan.md`) |
| Date Added | 2026-10-22 |
| Related Requirements | FR-2026-08-24-04, FR-2026-08-28-01, FR-2026-10-22-01, FR-2026-10-22-03, SR-2026-08-24-01, SR-2026-10-22-01 |

### Description

The `google_cloud_translate` provider shall implement the batch `replace` of FR-2026-10-22-01 by sending the texts that need translation in the `contents` field of one Google Cloud Translation Advanced v3 `translateText` request, using `mime_type` `text/plain`, and shall return one item per request text in request order. It shall verify that the response contains exactly one translation per sent text and otherwise raise `TextReplacementProviderError`. It shall use only `translateText`. It shall not use `batchTranslateText` or `translateDocument`, which require Cloud Storage and asynchronous operation (SR-2026-08-24-01).

Per text, the provider shall retain the behaviour of FR-2026-08-24-04. Empty text, and every text of a request whose source and target tags are equal after case-insensitive comparison, shall be returned unchanged with confidence `0.0` without an API call, and a request needing no API call shall make none. For filename requests it shall translate each filename stem, retain each suffix, and apply the same unsafe-stem checks. Every successful item shall have confidence `0.0`. FR-2026-08-28-01's prohibition on batching requests is superseded by this requirement; its client-reuse and initialization rules remain.

The provider shall split a request into one or more `translateText` calls according to its limits, which it shall expose as `batch_limits`. The defaults are a maximum of 1,024 texts per call, a soft target of 5,000 characters per call, and a hard maximum of 30,000 characters per call, where a character is a Python string code point. The target is soft: a single text longer than the target shall be sent alone. A text longer than the hard maximum shall be rejected with a safe diagnostic. These defaults shall be hard-coded and overridable by these environment variables:

| Variable | Default | Valid range |
|---|---|---|
| `GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_ITEMS` | 1024 | 1 to 1024 |
| `GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS` | 5000 | 1 up to the maximum-characters value |
| `GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_CHARACTERS` | 30000 | 1 to 30000 |

An unset or blank variable shall select its default. A non-integer value, or a value outside its range, shall fail when the provider is created with a safe message that names the variable and does not echo credentials. The limits shall be read once when the provider is created. They shall not be part of any cache key, so changing them never invalidates a cache. Setting the maximum item count to 1 shall reproduce one-text requests.

If a response item is missing, empty, or yields an unsafe filename stem, the provider shall retry that text alone once and raise the existing provider error only if that also fails. When a call containing more than one text fails with an error that request content could have caused, such as an invalid-argument response, the provider shall bisect the call to isolate the offending text and raise the existing provider error for that text only. Authentication, authorization, configuration, and daily-quota failures shall fail immediately without bisecting. Transient and rate-limit failures are governed by FR-2026-10-22-03 before any bisecting.

The remote data boundary of FR-2026-08-24-04 is unchanged: the provider shall send only the texts, source and target language tags, and configured project and API operation parameters. Its safe failure diagnostics shall add the text count and the total character count and shall not contain request text, translated text, credentials, or response bodies.

### Rationale

Measured Word, PDF, PowerPoint and Excel documents made about 6,900, 3,400, 1,800 and 220 sequential `translateText` calls (about 151,000, 88,000, 20,000 and 6,000 characters), taking about 770, 390, 210 and 32 seconds, or 0.11 to 0.15 seconds per call whatever the length. Latency per call, not payload size, dominated. Packing about 5,000 characters per request reduces the largest document to roughly 30 requests without changing per-character billing or per-text cache keys. Google documents a 1,024-item and a 30,000-code-point limit per request and recommends about 5,000 code points. Hard-coded defaults with environment overrides allow tuning without a code change.

### Verification

Automated tests shall use a mocked Google client and synthetic text only. They shall verify batch request construction and order, packing at each limit, a soft-target oversized text sent alone, rejection above the hard maximum, response-count mismatch, per-text recovery, bisection to a single offending text, immediate failure for non-content errors, unchanged empty and same-language shortcuts, filename stem handling, environment override and validation including blank and out-of-range values, and diagnostics free of text.

---

## FR-2026-10-22-03

| Property | Value |
|----------|-------|
| Title | Use a long request deadline and back off on Google Cloud Translation quota limits |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-10-22 |
| Related Requirements | FR-2026-09-03-04, FR-2026-10-22-02, FR-2026-10-22-06, FR-2026-10-22-07, SR-2026-10-22-01 |

### Description

The Google Cloud Translation provider's per-attempt `translateText` deadline shall default to 300 seconds, fixed regardless of payload size, and shall be overridable by `GOOGLE_CLOUD_TRANSLATION_TIMEOUT_SECONDS` with an integer from 1 through 3600. An unset or blank value shall select the default, and any other value shall fail when the provider is created. The three-attempt limit and the transient-failure rules of FR-2026-09-03-04 remain, and each limit applies per `translateText` request. Failure diagnostics shall add the request's text count and total character count to the existing safe fields, and shall still record the per-attempt deadline.

A per-minute quota response shall be treated as a rate limit, not as an ordinary failure. This means a `429 RESOURCE_EXHAUSTED` response, or a `403` response whose reason is `User Rate Limit Exceeded` (`rateLimitExceeded`). The provider shall retry the request after an exponential wait with jitter that starts at 2 seconds, doubles, and is capped at 60 seconds per wait, and shall honour a server-supplied retry delay when one is present. Rate-limit retries shall not count against the three-attempt limit. They shall continue until the request succeeds or the total wait for that request exceeds `GOOGLE_CLOUD_TRANSLATION_RATE_LIMIT_MAX_WAIT_SECONDS`, which shall default to 1800 seconds, accept an integer from 0 through 86400, and disable the backoff when it is 0. After the cap, the provider shall raise the existing safe provider error.

A `Daily Limit Exceeded` response shall fail immediately with its own safe reason code and a message stating that the daily quota is exhausted, because waiting minutes cannot clear a daily quota. A `403` response for any other reason, such as permissions, billing, or a disabled API, shall remain a non-transient failure.

Every rate-limit wait shall be visible and attributable without exposing content. The provider shall write a content-free log line stating the wait number, wait seconds, and text count, and the progress display shall show the label "Waiting for translation quota" while it waits (FR-2026-10-22-07). The run metrics of FR-2026-10-22-06 shall record the number of rate-limit waits and the total wait seconds separately from provider call duration. With `--debug`, a failure diagnostic shall record those two values.

### Rationale

The 10-second deadline was a fixed value that suited single-text requests but would fail a large batch. The time went into the number of requests, not the length of any one, so a longer deadline lets a request pass instead of failing early. The pipeline may run inside a larger service with several users translating at once, so reaching a shared quota slows a run down rather than failing it. Google's quota documentation defines the daily and per-minute quota errors but prescribes no retry policy or maximum wait, so the backoff schedule and the 30-minute cap are project choices.

### Verification

Automated tests shall use a mocked client and a fake clock, so no test sleeps. They shall verify the default and overridden deadline, rejection of an invalid override, that a rate-limit response backs off and then succeeds, the backoff schedule and server delay, that rate-limit retries do not consume attempts, that the total-wait cap raises the safe error, that a daily-limit and an unrelated `403` fail fast, and that logs and diagnostics contain no request text.

---
