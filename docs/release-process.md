# Release process

This guide describes how to publish a release. The authoritative behaviour is in
the requirements; this is the practical checklist.

- Release workflow, `main`-tip rule: TR-2026-09-10-02
- Changelog draft script: TR-2026-09-11-01
- Changelog entry published in GitHub Release notes: TR-2026-09-12-01

## How a release works

A release is a Git tag matching `vX.Y.Z` pushed to GitHub. The
[release workflow](../.github/workflows/release.yml) then:

1. Checks that the tag points at the **current tip of `main`**. Otherwise it fails.
2. Checks that `CHANGELOG.md` has an H2 entry whose version equals the tag
   without the leading `v`. Otherwise it fails before building anything.
3. Builds and pushes the CPU and GPU images to
   `ghcr.io/<owner>/visual-doc-pipeline-{cpu,gpu}`, tagged `vX.Y.Z` and `latest`.
4. Creates or updates the GitHub Release. The notes contain the changelog entry
   and a `## Container images` section.

The workflow never creates, moves or deletes tags. A failed run can be re-run for
the same tag.

Two consequences shape everything below:

- **The changelog entry must already be on `main` before you tag**, because the
  workflow reads `CHANGELOG.md` from the tagged commit.
- **Nothing else may merge to `main` between the changelog merge and the tag**,
  because the tag must be the tip of `main`.

`main` is protected, so all changes reach it through a pull request. Branch
protection is GitHub repository state and is not versioned in this repository.

## Preparing the changelog (both scenarios)

1. Make sure every requirement change for the release is **committed** on the
   branch. The draft script reads committed state: it diffs `requirements/` from
   the latest `vX.Y.Z` tag to `HEAD`. Uncommitted edits are ignored.
2. Make sure the tags are available locally (`git fetch --tags`) and `origin`
   is a GitHub URL.
3. Generate the draft:

   ```bash
   ./run.sh scripts/generate_changelog_draft.py          # next minor version
   ./run.sh scripts/generate_changelog_draft.py major    # next major version
   ```

   It prints the proposed tag and writes two gitignored files:
   `outputs/changelog-drafts/<version>.md` and
   `outputs/changelog-drafts/<version>.requirements.diff`. It never modifies
   `CHANGELOG.md`. Re-running overwrites both files.
4. Write the entry at the top of `CHANGELOG.md` from the draft (yourself or with
   an agent). Start with the draft's release H2 heading. The version text must
   exactly equal the tag's version. The date and any link text after it are free.
5. Commit the changelog on its own commit so it is easy to see in the history.

The heading's date is the day you ran the script, and its comparison link points
at a tag that does not exist yet (it works once the tag is pushed). If the PR
waits for days, update the date by hand.

## Scenario A: release from the feature branch you are about to merge

Use this when one feature PR is the whole release.

1. Finish the feature, including all requirement changes, and commit them.
2. Prepare the changelog on the same branch (see above) and commit it.
3. Open the PR, let CI pass, and merge it into `main`.
4. Do not merge anything else into `main` until the tag is pushed.
5. Update local `main` and tag the commit that is now the `main` tip. If you
   squash-merge, that is the squash commit, not one of your branch commits:

   ```bash
   git switch main
   git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

6. Watch the **Publish container release** workflow and check the GitHub Release.

If you add or change requirements after generating the draft, regenerate the draft
and update the changelog entry before merging.

## Scenario B: release branch collecting several PRs

Use this when several already-merged PRs, or several PRs merged in sequence,
make up one release, or when you want the release step reviewed separately.

1. Merge all the feature PRs into `main` first.
2. Create a short-lived branch from the updated `main`:

   ```bash
   git switch main
   git pull
   git switch -c feature/release-vX.Y.Z-changelog
   ```

3. Prepare the changelog on that branch (see above). The draft now covers every
   requirement change merged since the previous tag.
4. Open a PR containing only the `CHANGELOG.md` change, let CI pass, and merge it.
5. Do not merge anything else into `main` until the tag is pushed.
6. Tag the merge commit and push the tag exactly as in Scenario A step 5.

If a feature PR merges after you generated the draft, regenerate the draft and
update the changelog before merging the release PR.

If you instead want the release branch to accumulate the feature work itself
(feature PRs merged into a release branch, then one PR to `main`), treat that
final PR as Scenario A: generate the draft and write the changelog on the
release branch after the last feature merges into it.

## Before publishing

- Validate the GPU path manually on a compatible NVIDIA Linux host. CI cannot
  exercise GPU runtime behaviour (see the GPU validation requirement in
  `requirements/raster-ocr-requirements.md`).
- Confirm CI is green on `main`.

## If something goes wrong

| Situation | What happens | What to do |
|-----------|--------------|------------|
| Tag is not the `main` tip | Workflow fails at the first step | Delete the tag locally and on `origin`, then tag the current tip |
| No matching `CHANGELOG.md` entry | Workflow fails before any build | Merge a changelog fix to `main`, delete the tag, and tag the new tip |
| Image build or push fails | No GitHub Release is created; the other image may already be published | Re-run the workflow for the same tag; it republishes both variants and then creates the release |
| Release notes need correcting | Workflow-managed blocks are replaced on re-run; other content is preserved | Fix `CHANGELOG.md` on `main`, move the tag to the new tip, and re-run |

Because the tag must be the `main` tip, any fix to `CHANGELOG.md` means the tag
has to be recreated on the new tip. The workflow does not do this for you. If
immutable release tags matter, configure tag protection in the GitHub repository
settings; consider that when deciding how to recover.
