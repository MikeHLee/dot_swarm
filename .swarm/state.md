# State — SwarmCity

**Last touched**: 2026-04-01T00:00Z by human-ML + agent
**Current focus**: Distribution — PyPI + Homebrew publishing (Phase 4 CI/CD)
**Active items**: (none — paused, ready for pickup)
**Blockers**: PyPI Trusted Publishing not yet configured (manual step required)
**Ready for pickup**: SWC-003, SWC-004, SWC-005, SWC-006

---

## Handoff Note

Completed rename cleanup: all `swarm-city` references updated to `dot-swarm`, version numbers synced to 0.3.0 across `__init__.py`, `cli.py`, and publish workflow. Deprecated `/legacy/` PyPI endpoint removed. Pushed to main (commit 7953ea2).

Next step to unblock publishing: configure Trusted Publishing (OIDC) on PyPI at pypi.org/manage/project/dot-swarm/settings/publishing/ for repo MikeHLee/dot_swarm, workflow publish-pypi.yml. After that, tag v0.3.0 to trigger the publish workflow. Homebrew formula update follows once the PyPI tarball exists (need real SHA256).

