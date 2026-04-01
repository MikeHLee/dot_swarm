# Queue — SwarmCity (Organization Level)

Items are listed in priority order within each section.
Item IDs: `SWC-<3-digit-number>` — assigned sequentially, never reused.

---

## Active

(no active items)

## Pending

- [ ] [SWC-003] [OPEN] Configure Trusted Publishing (OIDC) on PyPI
      Manual step: pypi.org/manage/project/dot-swarm/settings/publishing/
      Repo: MikeHLee/dot_swarm · Workflow: publish-pypi.yml · Environment: (none)
      Blocks: SWC-004
      project: distribution

- [ ] [SWC-004] [OPEN] Tag and publish v0.3.0 to PyPI
      Run: git tag v0.3.0 && git push origin v0.3.0
      GitHub Actions workflow fires automatically on v* tag push
      Depends on: SWC-003
      project: distribution

- [ ] [SWC-005] [OPEN] Update Homebrew formula for dot-swarm v0.3.0
      File: swarm-city.rb.template
      - Rename package URL from swarm-city → dot-swarm
      - Bump version to 0.3.0
      - Replace SHA256 placeholder with real hash from PyPI tarball
      Depends on: SWC-004 (need live PyPI tarball for SHA256)
      project: distribution

- [ ] [SWC-006] [OPEN] Submit Homebrew formula to tap
      Decision needed: publish to homebrew-core or host own tap (e.g. MikeHLee/homebrew-dot-swarm)
      Depends on: SWC-005
      project: distribution

## Done

- [x] [SWC-001] [DONE · 2026-03-31T15:00Z] GUI for visualizing swarm trails in a GitHub repo
      project: visualizer
- [x] [SWC-002] [DONE · 2026-03-31T14:30Z] CLI commands `up` and `down` to manage alignment/relation of work items
      project: alignment
- [x] [SWC-003-pre] [DONE · 2026-04-01] Sync package name + version after dot_swarm rename
      Updated install docs (swarm-city → dot-swarm), versions (0.2.0 → 0.3.0), publish workflow
      Commit: 7953ea2
      project: distribution
