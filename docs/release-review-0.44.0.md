# v0.44.0 issue batch

Follow-up to the review of all seven issues left open after v0.43.0.

| Issue | Outcome |
| --- | --- |
| #367 | Fixed. Missing historical readings are excluded from consumption without discarding the underlying logs or costs. Existing zero readings need confirmation; newly entered zero readings are valid. CSV and backup round-trips retain reading presence. |
| #370 | Fixed. Maintenance History preserves last-known service snapshots across edits/deletion, records completions without requiring an expense, and includes existing maintenance expenses. Upgrade seeds the latest known snapshot, without inventing overwritten history. |
| #357 | Fixed. Front/rear pairs may remain fitted independently. Partial replacement of an all-axles fitting preserves the other pair and its mileage. All-axles replacement closes both pairs. |
| #371 | Partial fix; keep open. Feed failures now preserve prices and report source availability; ambiguous station matches and non-finite prices are rejected. The official Fuel Finder documentation could not be retrieved using direct requests or a browser, so the new authenticated API adapter is not included or advertised as supported. |
| #360 | Keep open. The reporter confirms that per-user sharing/defaults already exist. Their remaining request is for admins to see all vehicles. No permission expansion is made without an explicit access policy. |
| #373 | Keep open. External repair estimates need licensing, geographical coverage, and matching review. Existing manual estimated costs remain available. |
| #355 | Keep open. The named harness checkout is not available here; no stale PR branches are present in this checkout. |

## Data compatibility

One migration follows the existing head. Both Alembic and model-driven startup
recovery preserve fuel readings, default old tire fittings to all axles, and seed
one snapshot per existing maintenance schedule. A historical zero is not erased:
entering `0` on its edit form confirms it. Unknown readings inside a fill-to-fill
span prevent that span from contributing; other complete spans still count.

JSON and full backups include maintenance events, tire sets and axle-specific
fitting periods. Reimporting the same periods skips duplicates. Restoring into an
existing vehicle does not overwrite records or introduce conflicting active axle
fittings; skipped fitting periods are included in the restore summary.

## Validation

Regression coverage includes historical/explicit zero readings, unknown readings
inside fill spans, CSV input validation, snapshot retention, access isolation,
front/rear/all replacements, partial-set distance continuity, invalid fittings,
source failures, ambiguous matches, both upgrade paths, and JSON/full backup
round-trips. Desktop/mobile browser checks cover the new history page, tire axle
controls and blank historical readings. JavaScript checks also protect historical
Tessie readings from being replaced with today's value while editing.

Run the complete suite and the dev Docker workflow before merging one release PR.
No issue is closed solely because a partial improvement shipped.
