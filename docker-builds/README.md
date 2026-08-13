# docker-builds

Exported Docker/BuildKit build records (`.dockerbuild`) for notable image
builds of this fork. Each file is a gzipped OCI layout containing the build
history record, logs, and SLSA provenance for one build.

To inspect one, open it in Docker Desktop (Builds tab → Import build), or
run `docker buildx history import <file>`.

| File | Commit | Result |
|------|--------|--------|
| `mrmikeymarks~may~U08JJN.dockerbuild` | `f6ed8f7` — ci: boot a real server from every dev build and smoke-test it | `may-ci:f6ed8f7…` linux/amd64, succeeded in ~63 s (2026-08-07) |
