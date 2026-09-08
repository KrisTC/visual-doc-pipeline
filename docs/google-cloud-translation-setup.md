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

Further Google guidance: [Cloud Translation setup](https://docs.cloud.google.com/translate/docs/setup), [authentication](https://docs.cloud.google.com/translate/docs/authentication), [access control](https://docs.cloud.google.com/translate/docs/access-control), and [global and multi-regional endpoints](https://docs.cloud.google.com/translate/docs/advanced/endpoints).
