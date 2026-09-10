# v0.43.0 backlog review — 10 September 2026

Reviewed all seven open PRs and nine open issues in dannymcc/may. This batch
ships through dev, one dev-to-main PR, and one version tag/release.

## Pull requests

| PR | Outcome | Evidence / follow-up |
| --- | --- | --- |
| #294 | Include with corrections | Contributor separated MySQL work. Derive unit price from paid total plus discount; validate locale input. Fix manual-price browser event ordering, reject non-finite values, and handle omitted prices on edit while preserving explicit clearing and station-history removal. |
| #366 | Include | Correct German “Charging History” to “Ladeverlauf”; no catalogue keys or placeholders change. |
| #362 | Include | Gunicorn minimum 26.1.0 → 26.2.0; version-only change. Test with 26.2.0 installed. |
| #363 | Include | Coverage minimum 7.15.4 → 7.16.0; version-only change. Test with 7.16.0 installed. |
| #372 | Leave open | Adds PyMySQL and advertises MySQL/MariaDB, but no engine-specific CI, migration, backup/restore or upgrade evidence in the repository. Exercise both engines before claiming support. |
| #281 | Leave open | Migration cc6e159f098a duplicates existing trip fuel-level columns from f6a7b8c9d0e1 and branches migration history. Contributor has been asked to rebase and retain only remaining Tessie/import additions. |
| #320 | Leave draft/open | Primary-fuel separation is already implemented in current models and charts. The old patch also reports AdBlue consumption, contrary to current auxiliary-fluid rules, and lacks later bi-fuel distance attribution. Do not merge an older calculation over the newer one. |

## Issues

| Issue | Outcome | Evidence / follow-up |
| --- | --- | --- |
| #369 | Fixed in this release | Both Expenses by Category charts use one shared configuration: currency code on the value axis and tooltip, same palette and formatting. |
| #367 | Partially addressed; leave open | Both category charts now include accessible fuel and charging costs. Missing historical odometer readings still need a safe representation: imports can encode absence as zero, but zero can also be a real reading. Existing averages weight valid full-tank spans rather than averaging displayed zeroes. Do not rewrite historical readings or discard legitimate zero readings without distinguishing them. |
| #353 | Already completed; close after tests pass | GitHub confirms all five PRs (#263, #280, #288, #336, #337) merged on 23/25 August. Their version-only changes are present in current dev; the combined suite covers them. |
| #355 | Leave open | This checkout has no local pr-* or harness/pr-* branches. The issue concerns another harness checkout; its cleanup cannot be verified here. PR fetches in this review use force refspecs into origin/review-N, without deleting open PR branches. |
| #360 | Leave open | Explicit per-user sharing already exists at /vehicles/<id>/share, alongside instance sharing; Settings already has default_vehicle_id. The requested login destination is not fully provided. Review discoverability and landing-page behavior without broadening permissions. |
| #357 | Leave open | Tire fitment currently replaces open fitments without axle identity. Requires an axle-aware model, migration, simultaneous front/rear fitment rules and distance-history tests. A label alone would leave incorrect replacement behavior. |
| #370 | Leave open | Editing last_performed fields overwrites the schedule snapshot. Completion optionally creates a maintenance expense, including zero-cost work, which remains in history. An independent maintenance event history needs persisted events; past overwritten values cannot be reconstructed. |
| #371 | Leave open | Existing service consumes retailer JSON feeds; replacement Fuel Finder requires OAuth client credentials and a new API adapter. Keep certificate verification enabled. Need configured credentials, pagination/schema handling, matching and failure tests before replacing the source. |
| #373 | Leave open | External repair-cost estimates require review of licensing, geographic applicability, currency and vehicle/service matching before presenting them as a user's likely maintenance costs. No external service is enabled by this release. |

Government API reference: [Access fuel prices and forecourt data](https://www.gov.uk/guidance/access-the-latest-fuel-prices-and-forecourt-data-via-api-or-email).
The suggested estimate provider is [AutoRepairCost](https://autorepaircost.net/).

## Release gate

Run the entire Python suite, dependency consistency check, translation compilation
(via the suite), shared-chart/fuel-form JavaScript behavior checks and the dev CI
workflow before merging the release PR. The tagged workflow repeats tests before
publishing the production container. No separate per-change releases.
