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

The provider shall use the Google Cloud Translation Advanced v3 API's documented source- and target-language fields. It shall pass the request's BCP 47 tags unchanged unless the Google API requires a documented normalization. It shall configure the Google Cloud project through `GOOGLE_CLOUD_PROJECT`.

The provider shall use the global `translate.googleapis.com` endpoint and `global` location when `GOOGLE_CLOUD_TRANSLATION_LOCATION` is unset. When that setting names a Cloud Translation-supported location within continental Europe, such as `europe-west1`, the provider shall select the `translate-eu.googleapis.com` multi-regional endpoint and use that same location in its API resource names. A non-European location value shall raise `TextReplacementProviderError`; this feature does not support the US multi-regional endpoint. This feature shall use Google's pre-trained NMT model and shall not support custom AutoML models. The endpoint behavior and regional restrictions shall follow Google's [Global and multi-regional endpoints documentation](https://docs.cloud.google.com/translate/docs/advanced/endpoints).

Google Cloud credential configuration shall comply with SR-2026-08-24-01. A successful result shall use confidence `0.0`, because the API does not return a calibrated translation-confidence value for this operation. Empty input and requests whose source and target language tags are equal after case-insensitive comparison shall return the input unchanged with confidence `0.0` and shall not call the API.

The provider shall require the service-account Application Default Credentials configuration defined by SR-2026-08-24-01. Missing project or `GOOGLE_APPLICATION_CREDENTIALS` configuration, an unreadable credential file, or an API-key-only configuration shall raise `TextReplacementProviderError` before making a network request.

`google_cloud_translate` shall declare `LOCAL_EVALUATION_ELIGIBLE = False`. Automated local text-replacement evaluation and its default test suite shall not instantiate it or send evaluation text to Google. This evaluation exclusion does not prevent user-requested processing of confidential samples through the provider when it complies with SR-2026-08-24-01.

The provider shall send to Google only the replacement request's text and source and target language tags, plus the configured project and API operation parameters. It shall not send source paths, output paths, document metadata, OCR confidence, image bytes, evaluation artifacts, or credentials. It shall not persist translation text or API responses beyond the normal in-memory replacement result.

Provider-owned automated tests shall use synthetic text and filenames only. They shall mock the Google client and verify ordinary-text translation, filename safety, unchanged same-language and empty requests, global and EU endpoint configuration, configuration and API failures, API request construction, and that no confidential or credential value appears in errors or logs. Tests shall not make network calls or require Google credentials.

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

The project shall provide `scripts/configure_google_cloud_translation.py` to configure and verify the local Google Cloud Translation provider. The Python helper shall be invoked through the project's locked Python environment, for example `uv run --no-sync python scripts/configure_google_cloud_translation.py --credential-file ../credentials/credential.json`. It shall accept `--credential-file` with an absolute or relative path to a service-account credential JSON file and optional `--location`. The helper shall resolve a relative credential-file path against the invoking process's current working directory before validation, probing, and writing its absolute forward-slash form to `.env.local`. It shall derive the project ID from the credential file's `project_id` value. The optional location shall follow FR-2026-08-24-04: an unset location selects the global endpoint and a supported European location selects the EU endpoint. Its command help shall state that omission selects the global endpoint and list `europe-west1` (Belgium), `europe-west3` (Frankfurt), and `europe-west4` (Netherlands) as examples rather than an exhaustive availability list.

Before updating `.env.local`, the helper shall validate that the supplied path is an existing service-account credential JSON file, then perform one synthetic `translateText` request through the Google Cloud Translation provider using a fixed repository-owned test string. The probe shall confirm that the credentials, project, selected endpoint, and location work together. It shall not use sample data, document content, OCR output, user-provided text, or confidential data.

After a successful probe, the helper shall atomically create or update only its marked `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, and optional `GOOGLE_CLOUD_TRANSLATION_LOCATION` entries in the repository-root `.env.local` file. It shall write `GOOGLE_APPLICATION_CREDENTIALS` as a double-quoted absolute path with forward slashes, so the uv dotenv loader can parse a Windows credential-file path. It shall preserve all user-managed entries, including the CUDA `PATH` entry managed by `scripts/configure-paddle-cuda-environment.ps1`. If validation or the probe fails, it shall leave an existing `.env.local` unchanged and shall not create one that did not already exist.

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
data boundary, or expose configuration values in errors or logs.

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

---
