# ColorPro delivery

The user requires every completed ColorPro app release to be delivered through
the built-in updater. Local installers alone are not the final delivery.

- Follow `RELEASES.txt`: test the change, build both supported Windows channels,
  and publish a versioned GitHub release from the exact product-only source commit.
- Upload as a draft. Verify every asset size and SHA-256 plus both update manifests
  before publishing. Never replace assets in an already published release.
- Routine app releases must be compact file-level updates, not multi-gigabyte
  runtime reinstallations. Use build/compact.py and verify actual old-to-new
  installation without runtime downloads. A new PC needs one full Offline.exe;
  Setup.exe is update-only and must never download or run a baseline installer.
  Full installers skip identical files and must be tested offline and on rerun.
- Keep the pinned 1.2.1 runtime release available: already published 1.3.0
  bootstrap installers depend on it. Runtime changes require an explicit
  new baseline and migration tests, never a silently enlarged routine update.
- After publishing, check that the updater discovers the release for both channels
  and does not offer reinstalling the same version or downgrading a newer version.
- Keep photographs, local configuration, tokens and research/training state private.
- Publication does not authorize silently installing the app or closing the user's
  running applications. Installation remains a user action in ColorPro.
- If publishing is blocked, state that clearly; do not describe a local-only build
  as an available automatic update.
