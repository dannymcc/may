# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at 0.28.0. Notes for earlier releases are on the
[GitHub releases page](https://github.com/dannymcc/may/releases).

## [0.29.0] - 2026-08-23

### Added

- UK fuel prices. Admins can switch on the government fuel price feeds in
  Settings → Integrations → UK Fuel Prices; saved stations are then matched to
  forecourts by postcode and their prices recorded, feeding the existing price
  history and Cheapest Fuel screens. Refreshes run every six hours in the
  background, or on demand with the "Update UK Prices" button on the Fuel
  Stations page or a station's price history. No API key is needed, and the
  retailer feed list can be overridden.
  ([#258](https://github.com/dannymcc/may/issues/258))
- The vehicle PDF report lists the vehicle's parts and consumables, with type,
  specification, quantity and part number, alongside the existing
  specifications, fuel logs and expenses. Vehicles with no parts recorded are
  unchanged. ([#235](https://github.com/dannymcc/may/issues/235))

## [0.28.0] - 2026-08-23

### Added

- Vehicle PDF reports can now include receipt images. The vehicle page has a
  "PDF + Receipts" button alongside the existing "PDF" one; it appends the
  images attached to the fuel logs and expenses in the report. Anything that
  cannot be inlined — a PDF scan, a missing file, or one that would push the
  report past the 20 MB image budget — is listed at the end of the report
  rather than dropped silently.
  ([#219](https://github.com/dannymcc/may/issues/219))
- Expenses accept more than one receipt. Select several files when adding or
  editing an expense, and the expandable row in the expense list links to each
  one. Files rejected for an unsupported extension are now reported rather than
  dropped silently. ([#234](https://github.com/dannymcc/may/issues/234))
- API v1 endpoints for trips and charging sessions: list, create, read, update
  and delete under `/api/v1/vehicles/{id}/trips`, `/api/v1/trips/{id}`,
  `/api/v1/vehicles/{id}/charging` and `/api/v1/charging/{id}`, plus
  `/api/v1/trip-purposes` and `/api/v1/charger-types`. Documented at `/api/docs`.
  ([#295](https://github.com/dannymcc/may/issues/295))
- Dashboard charts label their value axis with your currency, and tooltips show
  it too. ([#289](https://github.com/dannymcc/may/issues/289))
- Initial Hungarian translation files, contributed by
  [@burgatshow](https://github.com/burgatshow). Hungarian is not yet offered in
  the language picker while the remaining strings are filled in.
  ([#290](https://github.com/dannymcc/may/pull/290))

### Fixed

- `.env` settings were silently ignored. `config.py` now loads the `.env` file
  sitting next to it before reading the environment. Real environment variables
  still take precedence, so Docker deployments are unaffected.
  ([#297](https://github.com/dannymcc/may/issues/297))
- Deleting an entry from the fuel log bounced you to the vehicle page; it now
  leaves you where you were. ([#298](https://github.com/dannymcc/may/issues/298))

### Changed

- The expense list loads attachments in a single query rather than one per row.
- README and `.env.example` corrected: the real defaults for `DATABASE_URL` and
  `UPLOAD_FOLDER` are inside the application directory, the `sqlite:///` versus
  `sqlite:////` distinction is spelled out, and there is a note that `.env` does
  not drive those two keys under Docker Compose.
- The supported languages table in the README now lists Arabic, Czech, Russian
  and Turkish, which were already available in the app.
- Dependencies: `psycopg2-binary` >= 2.9.12
  ([#280](https://github.com/dannymcc/may/pull/280)), `coverage` >= 7.15.4
  ([#288](https://github.com/dannymcc/may/pull/288)), and `actions/setup-python`
  bumped from 6 to 7 in CI ([#263](https://github.com/dannymcc/may/pull/263)).
