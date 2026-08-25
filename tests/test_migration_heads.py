"""Regression test: the alembic migration graph must have exactly one head.

Two migrations can end up with the same ``down_revision`` when they are
authored in parallel (e.g. two features branching off the same prior
migration) and neither is rebased onto the other with a merge revision. When
that happens ``flask db upgrade`` refuses to run ("Multiple head revisions
are present for given argument 'head'"), and docker-entrypoint.sh only logs
that failure rather than treating it as fatal, so a deploy can silently stop
tracking new migrations until someone notices and merges the heads by hand.

This walks the migration files directly via ``ast`` rather than importing
alembic/Flask, so it can run without the application's runtime dependencies
installed.
"""
import ast
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / 'migrations' / 'versions'


def _parse_revision(path):
    """Pull ``revision`` and ``down_revision`` out of a migration file's source."""
    tree = ast.parse(path.read_text(), filename=str(path))
    revision = None
    down_revision = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if 'revision' in targets:
            revision = ast.literal_eval(node.value)
        if 'down_revision' in targets:
            down_revision = ast.literal_eval(node.value)
    return revision, down_revision


def _migration_files():
    return sorted(p for p in MIGRATIONS_DIR.glob('*.py') if p.name != '__init__.py')


def test_migration_graph_has_a_single_head():
    files = _migration_files()
    assert files, 'expected migration files to be found under migrations/versions/'

    revisions = {}
    down_revisions = set()
    for path in files:
        revision, down_revision = _parse_revision(path)
        assert revision is not None, f'{path.name} has no revision id'
        revisions[revision] = path.name
        if down_revision is None:
            continue
        if isinstance(down_revision, (tuple, list)):
            down_revisions.update(down_revision)
        else:
            down_revisions.add(down_revision)

    heads = [rev for rev in revisions if rev not in down_revisions]

    assert len(heads) == 1, (
        'expected exactly one migration head, found branching heads: '
        + ', '.join(f'{rev} ({revisions[rev]})' for rev in heads)
        + '. Add a merge migration (down_revision = (<head1>, <head2>)) to join them.'
    )
