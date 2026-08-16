#!/usr/bin/env python
"""Helper for bulk-filling gettext catalogs.

Usage:
  python scripts/fill_po.py dump <lang>            # JSON list of entries needing work
  python scripts/fill_po.py apply <lang> <json>    # fill from {msgid: msgstr} JSON file
  python scripts/fill_po.py status <lang>          # counts

Entries needing work = untranslated + fuzzy (fuzzy entries are skipped by
pybabel compile, so they render as English at runtime).

apply validates that %(name)s / %s style placeholders in each translation
match the msgid, skips mismatches, clears fuzzy flags on filled entries,
and saves the catalog.
"""
import json
import re
import sys

try:
    import polib
except ImportError:  # dev-only dependency, not part of the runtime image
    sys.exit("polib is required: uv pip install --python venv/bin/python polib")

PLACEHOLDER_RE = re.compile(r'%\([^)]+\)[sdf]|%[sdf]|\{[^}]*\}')


def po_path(lang):
    return f'app/translations/{lang}/LC_MESSAGES/messages.po'


def needs_work(entry):
    return not entry.obsolete and entry.msgid and (
        not entry.msgstr or 'fuzzy' in entry.flags
    )


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, lang = sys.argv[1], sys.argv[2]
    if cmd == 'apply' and len(sys.argv) < 4:
        sys.exit('apply requires a JSON file argument')
    po = polib.pofile(po_path(lang))

    if cmd == 'dump':
        out = [
            {'msgid': e.msgid, 'suggestion': e.msgstr or None}
            for e in po if needs_work(e)
        ]
        print(json.dumps(out, ensure_ascii=False, indent=1))
    elif cmd == 'status':
        pending = sum(1 for e in po if needs_work(e))
        print(f'{lang}: {pending} entries need work')
    elif cmd == 'apply':
        with open(sys.argv[3], encoding='utf-8') as f:
            translations = json.load(f)
        filled = skipped = 0
        for e in po:
            if not needs_work(e) or e.msgid not in translations:
                continue
            msgstr = translations[e.msgid]
            if not msgstr or not isinstance(msgstr, str):
                continue
            if sorted(PLACEHOLDER_RE.findall(e.msgid)) != sorted(PLACEHOLDER_RE.findall(msgstr)):
                print(f'SKIP placeholder mismatch: {e.msgid!r} -> {msgstr!r}')
                skipped += 1
                continue
            e.msgstr = msgstr
            if 'fuzzy' in e.flags:
                e.flags.remove('fuzzy')
            filled += 1
        po.save()
        print(f'{lang}: filled {filled}, skipped {skipped}, '
              f'{sum(1 for e in po if needs_work(e))} still pending')
    else:
        sys.exit(f'unknown command {cmd}')


if __name__ == '__main__':
    main()
