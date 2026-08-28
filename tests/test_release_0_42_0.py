"""Release prep for 0.42.0: version bump and changelog (#354).

Six fixes queued for release (#347-#352) are on dev and verified there, but
dev still reports the previous release: APP_VERSION in config.py and
CHANGELOG.md's newest section both still say 0.41.4. The weekly auto-release
would otherwise ship these commits as an unlabelled continuation of 0.41.4.

This pins CLAUDE.md's "Creating a Release" steps 1-2 only: the version bump
and the changelog section. It does not touch tagging, main, or gh -- those
remain out of scope.
"""
import re
from pathlib import Path

import config

BASE_DIR = Path(__file__).resolve().parent.parent
CHANGELOG = BASE_DIR / 'CHANGELOG.md'

# The day 0.42.0 goes out on the weekly auto-release (#356).
RELEASE_DATE = '2026-09-02'


def _changelog_text():
    return CHANGELOG.read_text(encoding='utf-8')


def _section_0_42_0():
    text = _changelog_text()
    start = text.find('## [0.42.0]')
    assert start != -1, "CHANGELOG.md has no ## [0.42.0] section"
    end = text.find('\n## [', start + 1)
    return text[start:end if end != -1 else len(text)]


def test_app_version_is_bumped_to_0_42_0():
    assert config.APP_VERSION == '0.42.0'


def test_changelog_dates_0_42_0_to_the_release_date():
    # The date is the day 0.42.0 ships on the weekly auto-release, not the day
    # the section was written (#356). Asserting the exact date rather than the
    # YYYY-MM-DD shape is deliberate: a pattern check let a wrong date through
    # once already. If the release slips, this failing is the cue to re-date
    # the heading before cutting.
    assert re.search(
        rf'^## \[0\.42\.0\] - {re.escape(RELEASE_DATE)}$',
        _changelog_text(),
        re.MULTILINE,
    ), (
        f"CHANGELOG.md's 0.42.0 heading must read "
        f"'## [0.42.0] - {RELEASE_DATE}', the date the release ships"
    )


def test_0_42_0_section_sits_above_0_41_4():
    text = _changelog_text()
    new_pos = text.find('## [0.42.0]')
    old_pos = text.find('## [0.41.4]')
    assert new_pos != -1 and old_pos != -1 and new_pos < old_pos, (
        "the 0.42.0 section must be added above the existing 0.41.4 section"
    )


def test_0_42_0_section_references_all_six_issues():
    section = _section_0_42_0()
    missing = [n for n in (347, 348, 349, 350, 351, 352) if f'#{n}' not in section]
    assert not missing, f"0.42.0 section does not reference: {missing}"


def test_vendor_field_issue_is_not_filed_under_fixed():
    # #349 adds a new vendor field to the recurring-expense form -- a new
    # capability, not a fix -- so it must not appear under ### Fixed.
    section = _section_0_42_0()
    fixed_start = section.find('### Fixed')
    if fixed_start == -1:
        return
    next_heading = re.search(r'\n### ', section[fixed_start + 1:])
    fixed_end = (
        fixed_start + 1 + next_heading.start() if next_heading else len(section)
    )
    assert '#349' not in section[fixed_start:fixed_end], (
        "#349 (recurring-expense vendor field) is filed under ### Fixed; "
        "it is a new capability and belongs under Added/Changed instead"
    )
