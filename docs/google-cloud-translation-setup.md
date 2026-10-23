# Google Cloud Translation Setup

The `google_cloud_translate` provider uses Cloud Translation Advanced v3 with a local service-account credential JSON file. It does not support an API key.

Before configuring the provider, an authorized project administrator must enable billing and the Cloud Translation API, then grant the service account **Cloud Translation API User** (`roles/cloudtranslate.user`). Viewer, Editor, and Admin are not the required role for this provider.

Store the credential JSON file in an approved local folder outside the repository. Do not commit it, copy its contents into another repository file, or paste it into logs, chat, tests, or issue reports.

Run the helper with an absolute path or a path relative to your current directory. It resolves the path to an absolute path before probing and writing `.env.local`, reads the credential JSON's `project_id`, sends one fixed synthetic probe translation, and updates `.env.local` only after the probe succeeds:

```shell
uv run --no-sync python scripts/configure_google_cloud_translation.py --credential-file ../credentials/translation-service-account.json
```

`europe-west1` is the default EU location. To choose another continental-European location, pass it explicitly:

```shell
uv run --no-sync python scripts/configure_google_cloud_translation.py --credential-file /absolute/path/to/translation-service-account.json --location europe-west3
```

The helper writes `GOOGLE_APPLICATION_CREDENTIALS` as a quoted forward-slash path that uv can load on Windows. The provider derives its project from the credential JSON and defaults to `europe-west1`, so it does not write either corresponding environment variable unless a non-default location was explicitly requested. A manually supplied `GOOGLE_CLOUD_PROJECT` or `GOOGLE_CLOUD_TRANSLATION_LOCATION` remains an override. The helper preserves unrelated `.env.local` entries and migrates the former PowerShell helper's marked block. A failed credential validation or probe leaves the existing file unchanged.

## Batching, deadlines and quota

The provider translates many texts in one synchronous `translateText` request. It does not use `batchTranslateText` or `translateDocument`, so no Cloud Storage bucket is needed and only the texts, language tags and project parameters leave the machine. A document's texts are listed first and sent in batches, instead of one request per string. In a measured test against the real service, a request cost about 0.12 seconds plus about 11 milliseconds per 1,000 characters, and batches of 100 to 1,000 texts translated 90 to 320 times faster than one-text requests.

All of these environment variables are optional. An unset or blank value selects the default. An invalid value stops the provider from starting, with a message that names the variable. None of them affect cached results, so changing them never invalidates a cache.

| Variable | Default | Valid range | Purpose |
|---|---|---|---|
| `GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_ITEMS` | 1024 | 1 to 1024 | Most texts per request. Set to `1` to send one text per request (a rollback that needs no code change). |
| `GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS` | 5000 | 1 up to the maximum-characters value | Soft target of characters per request. A single longer text is sent alone. |
| `GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_CHARACTERS` | 30000 | 1 to 30000 | Hard maximum of characters (code points) per request, which is Google's limit. A longer single text is rejected. |
| `GOOGLE_CLOUD_TRANSLATION_TIMEOUT_SECONDS` | 300 | 1 to 3600 | Deadline for each `translateText` attempt. |
| `GOOGLE_CLOUD_TRANSLATION_RATE_LIMIT_MAX_WAIT_SECONDS` | 1800 | 0 to 86400 | Total time to wait out per-minute quota responses for one request. `0` disables the wait. |

The defaults follow Google's guidance of about 5,000 code points per request, within its limits of 1,024 texts and 30,000 code points. Larger requests gain little and repeat more text if one fails.

### Quota limits

If Google reports that the per-minute quota is exceeded (a `429 RESOURCE_EXHAUSTED` response, or a `403` for `User Rate Limit Exceeded`), the provider waits and retries instead of failing. The wait starts at 2 seconds, doubles with some jitter up to 60 seconds, and honours a longer delay when Google supplies one. These waits do not count towards the three-attempt limit for transient failures. The progress display shows "Waiting for translation quota", and the `--debug` run activity records the number of waits and the total wait time. When the total wait for a request passes the cap above, the run fails with a provider error. Google's quota documentation does not prescribe a retry policy or a maximum wait, so the backoff schedule and the 30-minute cap are project choices.

A `Daily Limit Exceeded` response fails immediately, because waiting minutes cannot clear a daily quota. A `403` for another reason, such as permissions, billing or a disabled API, also fails immediately. To raise a quota, see Google's [quotas and limits](https://docs.cloud.google.com/translate/quotas).

Further Google guidance: [Cloud Translation setup](https://docs.cloud.google.com/translate/docs/setup), [authentication](https://docs.cloud.google.com/translate/docs/authentication), [access control](https://docs.cloud.google.com/translate/docs/access-control), and [global and multi-regional endpoints](https://docs.cloud.google.com/translate/docs/advanced/endpoints).
