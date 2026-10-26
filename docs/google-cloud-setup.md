# Google Cloud provider setup

The `google_cloud_translate` text-replacement provider and `google_cloud_vision` OCR provider share a Google Cloud project, service-account credential file, and local configuration. Enable and grant access to each API you intend to use; configuring one does not enable the other.

Start with [shared credentials](#shared-project-and-credentials), then follow [Cloud Translation](#cloud-translation), [Cloud Vision OCR](#cloud-vision-ocr), or both.

## Shared project and credentials

Choose the Google Cloud project and confirm that [billing is enabled](https://console.cloud.google.com/billing). Obtain an approved service-account JSON credential file from the project administrator. Store it outside the repository or in a Git-ignored location. Do not commit it or copy its contents into logs, chat, tests, or issue reports. Neither provider supports an API key.

Set `GOOGLE_APPLICATION_CREDENTIALS` to the absolute path of that file in the repository-root `.env.local` or the process environment. Both providers derive the project ID from the file's `project_id` unless `GOOGLE_CLOUD_PROJECT` explicitly overrides it. See Google's [Application Default Credentials guide](https://docs.cloud.google.com/docs/authentication/provide-credentials-adc).

For manual configuration, use an approved path in the ignored `.env.local` file:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/to/service-account.json"
```

`GOOGLE_CLOUD_TRANSLATION_LOCATION` is also shared. When unset, Translation uses `europe-west1` through `translate-eu.googleapis.com`, while Vision uses the `eu` multi-region through `eu-vision.googleapis.com`. A supported continental-European Translation location such as `europe-west3` is used by Translation and mapped to Vision's `eu` multi-region. Vision does not offer individual `europe-west*` locations. Other values are rejected before a Vision request. See Google's [Translation endpoint guide](https://docs.cloud.google.com/translate/docs/advanced/endpoints) and [Vision OCR regional endpoint guide](https://docs.cloud.google.com/vision/docs/ocr).

If you use both providers, use the same credential file and project, enable both APIs, and grant both roles described below. The Translation configuration helper can write the shared `.env.local` settings, but it probes Translation; for Vision-only use, configure `.env.local` manually as shown above.

## Cloud Translation

In the selected project, an authorized administrator must enable the [Cloud Translation API](https://console.cloud.google.com/apis/library/translate.googleapis.com) and grant the service account **Cloud Translation API User** (`roles/cloudtranslate.user`) in **IAM & Admin → IAM**. Do not substitute the Cloud Translation Viewer, Editor, or Admin roles. See Google's [Translation setup](https://docs.cloud.google.com/translate/docs/setup), [authentication](https://docs.cloud.google.com/translate/docs/authentication), and [access-control](https://docs.cloud.google.com/translate/docs/access-control) guides.

To validate Translation and write the shared credential setting to `.env.local`, run the helper with an absolute path or a path relative to the current directory. It resolves the path, reads the credential file's `project_id`, sends one fixed synthetic translation, and updates `.env.local` only if the probe succeeds:

```shell
uv run --no-sync python scripts/configure_google_cloud_translation.py --credential-file ../credentials/translation-service-account.json
```

To choose another supported continental-European Translation location, pass it explicitly:

```shell
uv run --no-sync python scripts/configure_google_cloud_translation.py --credential-file /absolute/path/to/translation-service-account.json --location europe-west3
```

The helper writes the credential path as a quoted forward-slash path that uv can load on Windows. It writes a location only when a non-default one is requested, and it never writes `GOOGLE_CLOUD_PROJECT`. It preserves unrelated `.env.local` entries and migrates the former PowerShell helper's marked block. A failed credential validation or probe leaves the existing file unchanged.

### Batching, deadlines and quota

The provider translates many texts in one synchronous `translateText` request. It does not use `batchTranslateText` or `translateDocument`, so no Cloud Storage bucket is needed and only the texts, language tags and project parameters leave the machine. A document's texts are listed first and sent in batches, instead of one request per string. In a measured test against the real service, a request cost about 0.12 seconds plus about 11 milliseconds per 1,000 characters, and batches of 100 to 1,000 texts translated 90 to 320 times faster than one-text requests.

All of these variables are optional. An unset or blank value selects the default. An invalid value stops the provider from starting, with a message that names the variable. None of them affect cached results, so changing them never invalidates a cache.

| Variable | Default | Valid range | Purpose |
|---|---|---|---|
| `GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_ITEMS` | 1024 | 1 to 1024 | Most texts per request. Set to `1` to send one text per request (a rollback that needs no code change). |
| `GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS` | 5000 | 1 up to the maximum-characters value | Soft target of characters per request. A single longer text is sent alone. |
| `GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_CHARACTERS` | 30000 | 1 to 30000 | Hard maximum of characters (code points) per request. A longer single text is rejected. |
| `GOOGLE_CLOUD_TRANSLATION_TIMEOUT_SECONDS` | 300 | 1 to 3600 | Deadline for each `translateText` attempt. |
| `GOOGLE_CLOUD_TRANSLATION_RATE_LIMIT_MAX_WAIT_SECONDS` | 1800 | 0 to 86400 | Total time to wait out per-minute quota responses for one request. `0` disables the wait. |

The defaults follow Google's guidance of about 5,000 code points per request, within its limits of 1,024 texts and 30,000 code points. Larger requests gain little and repeat more text if one fails.

If Google reports that the per-minute quota is exceeded (a `429 RESOURCE_EXHAUSTED` response, or a `403` for `User Rate Limit Exceeded`), the provider waits and retries instead of failing. The wait starts at 2 seconds, doubles with some jitter up to 60 seconds, and honours a longer delay when Google supplies one. These waits do not count towards the three-attempt limit for transient failures. The progress display shows "Waiting for translation quota", and the `--debug` run activity records the number of waits and the total wait time. When the total wait for a request passes the cap above, the run fails with a provider error. Google's quota documentation does not prescribe a retry policy or a maximum wait, so the backoff schedule and the 30-minute cap are project choices.

A `Daily Limit Exceeded` response fails immediately, because waiting minutes cannot clear a daily quota. A `403` for another reason, such as permissions, billing or a disabled API, also fails immediately. To raise a quota, see Google's [quotas and limits](https://docs.cloud.google.com/translate/quotas).

## Cloud Vision OCR

In the selected project, an authorized administrator must **enable the Cloud Vision API** (`vision.googleapis.com`). This requires `serviceusage.services.enable`; the runtime service account does not need permission to enable APIs. Follow Google's [Vision setup guide](https://docs.cloud.google.com/vision/docs/setup).

In **IAM & Admin → IAM** for the same project, grant the service account **Service Usage Consumer** (`roles/serviceusage.serviceUsageConsumer`). This supplies `serviceusage.services.use` to consume project quota and billing. The Cloud Translation API User role serves Translation and does not replace this role in this setup. See Google's [Vision authentication guide](https://docs.cloud.google.com/vision/docs/authentication) and [Service Usage role reference](https://docs.cloud.google.com/iam/docs/roles-permissions/serviceusage).

The provider uses synchronous `DOCUMENT_TEXT_DETECTION` and sends image bytes directly to Vision. It needs no Cloud Storage bucket or Storage object role. To process a folder with Vision OCR, select `--ocr google_cloud_vision` in `scripts/folder_replacement.py`. For a local OCR evaluation, run:

```sh
./run.sh scripts/ocr_evaluations.py --ocr google_cloud_vision
```

To assess a smaller set, add one or more `--include` patterns matching source files relative to `sample-data/`:

```sh
./run.sh scripts/ocr_evaluations.py --ocr google_cloud_vision --include 'ja/example.pptx'
```

A selected document contributes all its embedded bitmap images. Repeated options and comma-separated patterns are supported. Only selected source files are prepared and evaluated; a filtered run replaces that provider's viewer with the selected set. Use a separate `--output-root` to keep viewers from several selections.

Open `outputs/evaluations/ocr/output/google_cloud_vision/index.html` to inspect the original recognized text. The separate `text-replacement.html` page shows local replacement previews translated to English. The OCR viewer marks recognized text as not translatable by the browser.

Without `--include`, the evaluator prepares the normal corpus from `sample-data/` and sends every eligible image, including confidential samples, to Google Cloud Vision. Its results remain under the ignored `outputs/evaluations/ocr/output/google_cloud_vision/` directory. Running `ocr_evaluations.py` without `--ocr` excludes the Cloud Vision provider. The evaluator's text-replacement stage uses only locally eligible replacement providers.

The provider derives regions from Cloud Vision words, detected breaks, and word geometry. It groups text on one visual line, while separating adjacent text at a clearly different size. Text wrapped onto another line is returned as another region. The evaluator displays detected line breaks in extracted text.

The provider omits Vision language hints so the service automatically detects languages in mixed-language images. The source language inferred from the input folder still labels OCR results and drives the local replacement preview.

The provider currently declares `en` and `ja`. It rejects images that cannot fit the synchronous API's image or dimension limits; it does not upload images through Cloud Storage. Google's [data-use FAQ](https://docs.cloud.google.com/vision/docs/data-usage) describes content handling and temporary request-metadata logging. Confirm that the configured project and the organization's data-handling rules permit each intended input.
