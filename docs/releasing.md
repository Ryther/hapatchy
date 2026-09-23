# Release procedure

The first release is not yet published. Repository publication, tags, GitHub
releases and acceptance involving GitHub/HACS credentials require owner action
or explicit authorization. Do not infer a release from a local passing suite.

1. Keep `custom_components/hapatchy/manifest.json` and `pyproject.toml` versions
   equal. Review `hacs.json` minimum HA against tested APIs and both locked lanes.
2. Run `.github/workflows/tests.yaml` in clean independent environments and run
   the pinned hassfest job in `.github/workflows/validation.yaml`. Inspect both
   failures and skipped external checks. Run the Dev Container lifecycle checks.
3. Review `git status --untracked-files=all`, the staged inventory and whitelist
   behavior. Never force-add local state, credentials, logs or planning captures.
4. Build a reviewable archive with `python script/build_release.py`. Inspect its
   inventory and SHA-256. The archive contains integration files plus the license;
   it must contain no development state. Local archives are ignored.
5. Once authorized, publish the repository. Run HACS repository validation
   against the actual public repository and resolve its findings. In disposable
   minimum and recent HA installations, install through HACS, restart and test
   native entry/subentry creation, actions, Repairs and diagnostics.
6. In disposable HA, capture a real HACS upstream update and verify exact
   reapplication or a safe conflict, backup retention, watcher recovery and no
   duplicate observers. A copied-file replay alone is insufficient evidence.
7. Record commit, HA/Python/HACS and upstream versions, hashes and results. Add
   sanitized real UI screenshots to the README and verify all public links.
8. After all acceptance gates pass and publication is authorized, create the
   matching version tag and GitHub release using the reviewed commit. Include
   compatibility, limitations and recovery guidance in release notes. Verify
   HACS can discover/download the release. Only then add working release badges
   or an installation link to the README.

Uninstall is not rollback: removing HAPatchY leaves patches and backups intact.
Use the checked revert action when applicable; never restore an old backup over
unknown upstream changes without reviewing them.
