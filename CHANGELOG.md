# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at 0.28.0. Notes for earlier releases are on the
[GitHub releases page](https://github.com/dannymcc/may/releases).

## [Unreleased]

## [0.41.0] - 2026-08-25

### Added

- Each fill-up of a dual-fuel vehicle can record the **distance run on this
  fuel** since the last fill-up of it, entered in the vehicle's own unit. The
  odometer alone cannot say which miles were run on which fuel, so this is the
  only way to work out a consumption figure for a stretch of history in which
  both fuels were used. The field appears only for vehicles that genuinely burn
  two fuels.
- The fuel type and the distance attributed to it are included in the CSV and
  JSON exports and in backups, so a dual-fuel history survives a restore, and
  both `fuel_type` and `fuel_distance` can now be set on a fill-up over the REST
  API as well as read. ([#221](https://github.com/dannymcc/may/issues/221))

### Fixed

- A dual-fuel vehicle — a petrol car converted to run on LPG, say — now gets a
  separate average consumption for each fuel on its vehicle page, instead of
  one figure that mixed petrol litres and LPG litres over the same odometer
  span and so described neither.

  This is a visible change for dual-fuel vehicles: a stretch of history where
  both fuels were used will explain that the figure cannot be worked out,
  rather than showing an average derived from the wrong distance. To restore
  the figure, edit those fill-ups and enter the distance run on that fuel
  since the previous fill-up of it. Only stretches that actually mix the two
  fuels are affected — a car converted to LPG last year keeps its ordinary
  figures for the years it ran on petrol alone — and everything else on the
  page (totals, spend, price history and the per-fill-up records) is
  unchanged. Vehicles running a single fuel are unaffected, as are diesels
  tracking AdBlue, which propels nothing.
  ([#221](https://github.com/dannymcc/may/issues/221))

## [0.40.0] - 2026-08-25

### Changed

- The last places that still described an hour-metered vehicle's readings as a
  distance now follow the vehicle, completing the work started in #282. The
  trip and charging forms ask for engine hours rather than an odometer
  reading, as the fuel, expense, note, tyre and allowance forms already did,
  and the remaining forms now change the word as well as the unit beside it.
  The CSV exports state each row's own unit, so a tractor's engine hours are
  no longer filed under a distance heading alongside the cars, and the Home
  Assistant endpoints report the unit the reading is actually in. Totals that
  span both kinds of vehicle — the dashboard and the trip summaries — say
  "mixed units" instead of adding engine hours to miles and labelling the sum
  as a distance. Distance-metered vehicles are unchanged throughout.
  ([#324](https://github.com/dannymcc/may/issues/324))

## [0.39.0] - 2026-08-25

### Added

- A maintenance schedule for a vehicle tracked in engine hours is now set in
  hours — "every 250 hours" — rather than in kilometres or miles. The only
  reading-based intervals on offer were distances, and the next-due reading
  was worked out by running that distance through the km/mi conversion before
  adding it to a figure that was in hours, so a tractor could never be
  serviced to anything sensible. The km and miles boxes are hidden for such a
  vehicle and shown again for any other, before any script runs.
  ([#282](https://github.com/dannymcc/may/issues/282))

### Fixed

- Readings on an hours-tracked vehicle, and every figure derived from them,
  are labelled in hours rather than in distance: "h" beside a reading,
  "L / h" for consumption, "Cost per h", "kWh / 100 h", and "Engine hours"
  rather than "Odometer" on the maintenance form. The figures have been right
  since 0.36.1; only the labels beside them still said "mi" or "L/100km".
  Fuel, expenses, notes, tyres, mileage allowance, the vehicle page, the
  maintenance list, the calendar feed and the PDF report all follow the
  vehicle's own unit now. The trip and charging forms, and the timeline on the
  vehicle page, still label the reading with the account's distance unit, as
  they do for every vehicle.
  ([#282](https://github.com/dannymcc/may/issues/282))

- "Due soon" for a maintenance schedule on an hours-tracked vehicle means
  within 25 engine hours rather than within 500, which had put every such
  service permanently in the amber.
  ([#282](https://github.com/dannymcc/may/issues/282))

- The next-due reading in the maintenance list is labelled with the owning
  vehicle's unit rather than the account's distance preference, which was
  also wrong for any vehicle whose own odometer unit differed from it.
  ([#282](https://github.com/dannymcc/may/issues/282))

## [0.38.2] - 2026-08-25

### Changed

- Charging sessions logged on the same date are now listed in odometer order,
  the highest reading first, rather than in whatever order the database
  returned them — the same fix #325 made for trips. A session's date carries no
  time of day, so several charges on one day could appear out of sequence,
  which is easy to hit on a plug-in hybrid. The list is still ordered by date,
  most recent first. A session with no odometer recorded has nothing to order
  by, so it is left wherever the database puts it within that date.
  ([#329](https://github.com/dannymcc/may/issues/329))

## [0.38.1] - 2026-08-24

### Fixed

- The "L/100km" and "km/L" choices in Settings > Units & Values were the two
  options #310 missed: still hard-coded English, so they stayed as written
  whatever language was selected. They now go through the catalogues, which
  lets locales use their own convention — Hungarian, for instance, spaces the
  unit as "L/100 km". Translations are filled in for all shipped languages.
  ([#328](https://github.com/dannymcc/may/issues/328))

### Changed

- The test suite no longer emits thousands of deprecation warnings. The causes
  are fixed rather than silenced: a shared `app.utils.utcnow()` replaces
  `datetime.utcnow()` throughout (still naive UTC, matching every stored
  column), primary-key lookups use `db.session.get()` and `db.get_or_404()`
  instead of the legacy 1.x query API, and the deliberate user/vehicle foreign
  key cycle is marked `use_alter`. Behaviour is unchanged; a real failure is now
  legible in the CI log. ([#302](https://github.com/dannymcc/may/issues/302))
- README: the sales tax notes now say that quick entry mode does not ask for
  tax, so a fill-up logged that way leaves the yearly total short until the log
  is edited.

## [0.38.0] - 2026-08-24

### Added

- Fuel logs can record the sales tax paid on a fill-up — VAT, GST/HST/PST or
  whichever applies locally — entered as the amount on the receipt and counted
  as part of the total cost, not added to it. Where a jurisdiction charges more
  than one tax, enter the sum. The fuel log list totals the tax by calendar
  year and shows each fill-up's share under its cost, and the amount is
  included in the vehicle PDF report, the CSV and JSON exports, backups, CSV
  imports and the REST API.
  ([#225](https://github.com/dannymcc/may/issues/225))

### Fixed

- Adding a fuel log with an invalid number in any field returned a server error
  instead of the validation message: the handler tried to re-render a template
  that does not exist. It now returns to the form with the message shown.

## [0.37.0] - 2026-08-24

### Changed

- Trips logged on the same date are now listed in odometer order, the highest
  reading first, rather than in whatever order the database returned them. A
  trip's date carries no time of day, so several journeys on one day could
  appear out of sequence and the reading on the top row would not be the
  vehicle's latest — easily missed on a phone. The list is still ordered by
  date, most recent first.
  ([#325](https://github.com/dannymcc/may/issues/325))

## [0.36.1] - 2026-08-24

### Fixed

- A vehicle set to track engine hours has its readings treated as hours rather
  than as a distance. Its consumption is worked out in litres per hour, its
  running cost per hour, and a charged machine's energy use per 100 hours;
  none of those figures change any more when the vehicle's (distance-only)
  odometer unit is switched between km and miles, which used to scale 50
  engine hours into 80.5 as though they were miles. Vehicles tracked by
  mileage are unaffected. The labels shown alongside these figures still read
  in distance terms and are being corrected separately.
  ([#323](https://github.com/dannymcc/may/issues/323))

### Changed

- A vehicle's tracking unit can no longer be changed once anything has been
  logged against its odometer. Switching it would have reinterpreted every
  existing reading — 50 miles becoming 50 engine hours — so the rest of the
  edit saves and that one field is refused with a message.
  ([#323](https://github.com/dannymcc/may/issues/323))

- The README documents the tracking unit, including the note that the figures
  for an hours-tracked vehicle are correct while the labels beside them still
  read in distance terms. The API documentation says the same about
  `total_distance` and `average_consumption`, and that the tracking unit is
  neither exposed nor settable over the API.
  ([#323](https://github.com/dannymcc/may/issues/323))

- The vehicle response example in the API documentation includes
  `secondary_fuel_type`, which the API has returned since 0.36.0.

## [0.36.0] - 2026-08-24

### Added

- "AdBlue/DEF" is offered as a secondary fuel type, so the fluid a diesel
  tracks alongside its fuel can be named rather than logged as "Other". It
  counts as no tailpipe CO2, being an exhaust additive rather than a fuel.
  ([#319](https://github.com/dannymcc/may/issues/319))

- The Fuel Logs table shows the fuel type of each entry.
  ([#319](https://github.com/dannymcc/may/issues/319))

- Fuel logs returned by the REST API now carry a `fuel_type` field, and each
  point of the vehicle stats consumption series is labelled with the fuel it
  belongs to. Fuel type remains read-only over the API: a log created there
  takes the vehicle's own fuel type.
  ([#319](https://github.com/dannymcc/may/issues/319))

### Fixed

- Fuel consumption is now worked out per fuel type, so an AdBlue refill logged
  against a diesel no longer inflates that diesel's L/100km. The previous
  full-tank lookup, the litres counted in between and the consumption average
  all consider one fuel at a time, and the Fuel Consumption Trend draws a
  separate labelled line for each. Logs recorded before the fuel type selector
  existed count as the vehicle's own fuel type.
  ([#319](https://github.com/dannymcc/may/issues/319))

## [0.35.3] - 2026-08-24

### Fixed

- An empty `.secret_key` file in May's data folder no longer leaves every
  worker process signing sessions with a key of its own, which showed up as
  forms — creating a user, say — being refused with "The CSRF session token is
  missing" or doing nothing at all. May now fills in a key file that exists but
  holds nothing, instead of leaving it as it found it.
  ([#315](https://github.com/dannymcc/may/issues/315))

## [0.35.2] - 2026-08-24

### Fixed

- Running without `SECRET_KEY` set no longer bounces you back to the login page
  on every page change. May now generates a key on first start and saves it to
  `.secret_key` in its data folder, so all of its worker processes sign
  sessions with the same key and logins survive a restart. Setting `SECRET_KEY`
  yourself still takes precedence, and if the key file cannot be written May
  starts as before with a warning.
  ([#317](https://github.com/dannymcc/may/issues/317))

### Changed

- The README's configuration section notes that the supplied
  `docker-compose.yml` passes a placeholder `SECRET_KEY`, so Compose users get
  that rather than a generated key until they set or remove it.

## [0.35.1] - 2026-08-24

### Fixed

- Several pages ran off the right-hand side on a phone. The rows of action
  buttons at the top of the vehicle, trips, stations and document pages now
  wrap onto a second line instead of dragging the page wider than the screen,
  and the tyre fitting history, expenses spend-by-vendor, user management and
  backup preview tables scroll sideways like every other table rather than
  overflowing or being clipped.
  ([#314](https://github.com/dannymcc/may/issues/314))

## [0.35.0] - 2026-08-24

### Changed

- Deleting a fuel log accepts the same `return_to=vehicle` parameter the new
  and edit fuel routes take, so the vehicle page now says where it wants to be
  sent back to rather than relying on the default. The older `next` parameter
  still works exactly as before, so existing links and bookmarks are
  unaffected. ([#312](https://github.com/dannymcc/may/issues/312))
- The README's fuel logs section says where deleting a log leaves you.

## [0.34.1] - 2026-08-24

### Fixed

- The Date Format, Distance, Volume and Fuel Consumption choices in Settings >
  Units & Values are now translated. They were hard-coded English, so they
  stayed in English whatever language was selected — obvious on a non-Latin
  catalogue. Translations for the new labels are filled in for all shipped
  languages. ([#310](https://github.com/dannymcc/may/issues/310))
- The Hungarian catalogue was marked fuzzy in its header, so `pybabel compile`
  skipped it and its `.mo` file could not be rebuilt in place. The marker is
  gone and the catalogue compiles with the rest.

### Changed

- The distance option in Settings reads "Kilometres (km)", matching the
  per-vehicle odometer picker and reusing its existing translations.

## [0.34.0] - 2026-08-24

### Added

- Outstanding reminders now carry a "Log expense" action. It opens the expense
  form pre-filled with the reminder's vehicle, title and a matching category;
  saving the expense completes the reminder and schedules its next occurrence.
  The cost is entered at that point rather than stored on the reminder, so fees
  that change between payments stay accurate.
  ([#296](https://github.com/dannymcc/may/issues/296))

### Changed

- The reminders list and the expense form now complete a reminder through the
  same code, so both roll a recurrence forward identically and keep the
  duplicate guard added for [#232](https://github.com/dannymcc/may/issues/232).
- The README's reminders section describes the new action.

## [0.33.2] - 2026-08-24

### Fixed

- Saving an expense, fuel log or note no longer always lands on the vehicle
  page. Each now returns to its own list, so several entries can be added one
  after another. Starting from a vehicle page still returns you to that
  vehicle, as before. ([#283](https://github.com/dannymcc/may/issues/283))

### Changed

- The README describes where saving a fuel log, note or expense leaves you.
- Tests cover both directions for expenses, fuel logs and notes: adding or
  editing from a list returns to that list, and doing the same from a vehicle
  page returns to the vehicle.

## [0.33.1] - 2026-08-23

### Fixed

- Hungarian can now be chosen. The translation contributed by
  [@burgatshow](https://github.com/burgatshow) in
  [#290](https://github.com/dannymcc/may/pull/290) is now complete, but the
  language code was never added to the list the settings picker and Babel read
  from, so it did not appear in Settings and was never negotiated for browsers
  asking for it. ([#300](https://github.com/dannymcc/may/issues/300))

### Changed

- The supported languages table in the README now lists Hungarian, and the
  README explains that a new catalogue must also be registered in `LANGUAGES`
  before it can be selected.
- A test checks that every translation catalogue shipped in
  `app/translations/` is listed in `LANGUAGES` and that every listed language
  has a compiled catalogue behind it, so the two cannot drift apart again.

## [0.33.0] - 2026-08-23

### Added

- Tire sets. A vehicle can now own several sets of tires — summer, winter,
  all-season — each with its type, size, purchase date, purchase odometer and
  cost. Putting a set on or taking it off records the date and the odometer
  reading, and the distance covered on each set is the sum of every period it
  spent fitted, counting up to the vehicle's latest reading while the set is
  still on. Fitting a set takes whichever set is on the vehicle off at the
  same reading, so a seasonal swap is one action. Sets can be retired when
  worn out or sold, and the area can be hidden from the menu like the others.
  ([#293](https://github.com/dannymcc/may/issues/293))
- An expenses-by-category chart on each vehicle page, breaking that vehicle's
  spending down the way the dashboard chart does for the fleet as a whole. It
  sits with the other vehicle charts, remembers whether it was collapsed, and
  is shown for electric vehicles as well. Vehicles with no expenses recorded
  do not show it. ([#287](https://github.com/dannymcc/may/issues/287))

## [0.32.0] - 2026-08-23

### Added

- User roles. Each account now carries a role that an administrator sets when
  creating or editing the user: Editor (full access, the default and what
  every existing account keeps), Contributor (may record fuel fill-ups and
  charging sessions, everything else read-only) or Viewer (may see the data
  but change nothing). Administrators are unaffected and always have full
  access. The rules are applied to the web interface, the REST API and the
  Home Assistant endpoints alike, and controls the account cannot use are
  hidden rather than left to fail. What an account can see is unchanged and
  still follows vehicle ownership and sharing.
  ([#285](https://github.com/dannymcc/may/issues/285))
- Notes and attachments on the vehicle timeline. Each timeline entry now shows
  the note recorded against it, and fuel logs and expenses list their
  attachments as links, so the timeline can be read without opening every
  entry in turn. ([#284](https://github.com/dannymcc/may/issues/284))

### Fixed

- An odometer recorded against an expense, such as the reading taken at an oil
  change, now counts towards the vehicle's latest odometer. Previously only
  fuel logs, trips and charging sessions were considered, so registering
  maintenance left the last reading unchanged.
  ([#286](https://github.com/dannymcc/may/issues/286))

### Changed

- The API documentation page now describes what an API key may do under each
  role, and lists the `permission_denied` error code alongside `forbidden`.

## [0.31.0] - 2026-08-23

### Added

- Fuel level on trips. A trip can now record the fuel gauge reading at each
  end, as a percentage of a full tank, alongside the odometer readings. Where
  the vehicle has a tank capacity set, May works out the fuel used on the trip
  from the two readings and shows it on the trip list and while the trip is
  being logged, giving a per-trip picture of consumption rather than only one
  per fill-up. Both readings are optional, are carried in the API, CSV import
  and export, and the backup. ([#273](https://github.com/dannymcc/may/issues/273))

### Changed

- The README feature list now mentions trip logging, which was missing from it.

## [0.30.0] - 2026-08-23

### Added

- Restoring a May backup. Settings → Integrations → Import Data now has a
  "Restore May Backup" option that accepts both the JSON export and the full
  backup ZIP produced by the export page, so data can be moved from an old
  instance into a new one. Documents, attachments and vehicle images come
  across from a full backup ZIP; a JSON export carries the records only.
  The restore always merges into the signed-in account: nothing is deleted or
  overwritten, and records already present are skipped rather than duplicated.
  A preview showing exactly what will be added is displayed before anything is
  written. ([#265](https://github.com/dannymcc/may/issues/265))
- A photo gallery for vehicles. The vehicle page has a "Photos" section that
  takes as many photos as you like, several at a time; any of them can be made
  the main photo shown on the dashboard and vehicle list, and the header image
  steps through the rest with left and right arrows. Photos are stored as
  attachments against the vehicle, so they are already covered by the full
  backup export. Deleting a vehicle removes its photos; deleting the main one
  falls back to another photo, or clears the image if none are left.
  ([#147](https://github.com/dannymcc/may/issues/147))

### Changed

- Saved fuel stations now remember which forecourt a live price feed matched
  them to, rather than re-deriving it from postcode and address on every
  refresh. A station therefore keeps reporting the same forecourt after its
  postcode is edited, and a forecourt that drops out of the feed is reported as
  unmatched instead of quietly resolving to a different one. This is
  groundwork for the Tankerkönig integration; live German prices are not
  available yet. ([#155](https://github.com/dannymcc/may/issues/155))

### Fixed

- Hybrid fill-ups no longer appear as a "hybrid" series in the fuel station
  price charts. Hybrid is how a vehicle is driven, not what goes in the tank,
  so a fill-up is now recorded against petrol by default; the fuel type
  selector on the fuel form is offered for hybrids and plug-in hybrids so
  diesel hybrid owners can pick diesel instead. Changing a saved log's fuel
  type now moves its price history row to match. Existing price history is
  left as it stands. ([#268](https://github.com/dannymcc/may/issues/268))

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
