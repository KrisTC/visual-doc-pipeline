# Google Cloud Translation Setup

The `google_cloud_translate` provider uses Cloud Translation Advanced v3 with a local service-account credential JSON file. It does not support an API key.

Before configuring the provider, an authorized project administrator must enable billing and the Cloud Translation API, then grant the service account **Cloud Translation API User** (`roles/cloudtranslate.user`). Viewer, Editor, and Admin are not the required role for this provider.

Store the credential JSON file in an approved local folder outside the repository. Do not commit it, copy its contents into another repository file, or paste it into logs, chat, tests, or issue reports.

Run the helper with the absolute path to that file. It reads the credential JSON's `project_id`, sends one fixed synthetic probe translation, and updates `.env.local` only after the probe succeeds:

```powershell
.\scripts\configure-google-cloud-translation.ps1 -CredentialFile 'C:\CredentialStore\translation-service-account.json'
```

To use the EU multi-regional endpoint, pass a continental-European location such as `europe-west1`:

```powershell
.\scripts\configure-google-cloud-translation.ps1 -CredentialFile 'C:\CredentialStore\translation-service-account.json' -Location europe-west1
```

The helper writes `GOOGLE_APPLICATION_CREDENTIALS` as a quoted forward-slash path that uv can load on Windows, derives and writes `GOOGLE_CLOUD_PROJECT`, and writes `GOOGLE_CLOUD_TRANSLATION_LOCATION` only when specified. It preserves unrelated `.env.local` entries. A failed credential validation or probe leaves the existing file unchanged.

Further Google guidance: [Cloud Translation setup](https://docs.cloud.google.com/translate/docs/setup), [authentication](https://docs.cloud.google.com/translate/docs/authentication), [access control](https://docs.cloud.google.com/translate/docs/access-control), and [global and multi-regional endpoints](https://docs.cloud.google.com/translate/docs/advanced/endpoints).