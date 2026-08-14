"""Pluggable enrichment: decompose free text into structured sidecar fields.

An enricher reads an ``EnrichmentContext`` (summary, description, location,
categories, attachments...) and returns ``{field: DerivedValue}``. Fields need
not have a typed column -- anything unknown is stored in ``sidecar.derived``
and surfaced to clients as ``X-MAY-D-<FIELD>``, so a new extraction can ship
without a migration.

Three invariants, in order of importance:

1. **A derived value never overwrites a user-set one.** ``sidecar.locked_fields``
   is checked before every write. This is the difference between a system
   people trust and one they turn off.
2. **Every derived value carries its provenance** -- which enricher, which
   version, what confidence, what evidence, when. You can always answer
   "why does this task say 90 minutes?"
3. **Enrichment is idempotent and cheap to skip.** The pipeline is keyed on a
   digest of the text it reads, so an unchanged event polled every 15 minutes
   by DAVx5 is enriched once, not ninety-six times a day.

Registering your own::

    from app.caldav.enrichment import Enricher, DerivedValue, register

    @register
    class InvoiceEnricher(Enricher):
        name = 'invoice'
        version = '1'
        fields = ('invoice_total', 'invoice_due')

        def run(self, ctx):
            ...
            return {'invoice_total': DerivedValue(1234.50, confidence=0.8)}
"""

import logging
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from string import Template
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Fields that are lists; derived values union with what is already there
# instead of replacing it.
LIST_FIELDS = ('contexts', 'blocked_by', 'blocks')

# Typed columns an enricher is allowed to populate. Anything else goes to
# sidecar.derived only. Telemetry is deliberately absent: it is computed, not
# inferred.
TYPED_FIELDS = (
    'estimate_minutes', 'actual_minutes', 'energy', 'contexts',
    'source_url', 'source_ref', 'source_system', 'blocked_by', 'blocks',
)


@dataclass
class DerivedValue:
    """A value some algorithm produced, with everything needed to defend it."""

    value: Any
    confidence: float = 0.5
    source: str = ''          # enricher name, filled in by the pipeline
    model: Optional[str] = None   # e.g. 'regex:duration/2' or 'claude-sonnet-5'
    evidence: Optional[str] = None  # the substring that triggered it

    def as_meta(self):
        return {
            'value': self.value,
            'confidence': round(float(self.confidence), 3),
            'source': self.source,
            'model': self.model,
            'evidence': self.evidence,
            'computed_at': datetime.utcnow().isoformat(),
        }


@dataclass
class EnrichmentContext:
    """Everything an enricher is allowed to read."""

    uid: str
    component: str = 'VTODO'          # VEVENT | VTODO | VJOURNAL
    summary: str = ''
    description: str = ''
    location: str = ''
    url: str = ''
    categories: List[str] = dc_field(default_factory=list)
    due: Optional[datetime] = None
    dtstart: Optional[datetime] = None
    raw_ics: str = ''
    user_id: Optional[int] = None
    # Existing sidecar state, read-only from an enricher's point of view.
    sidecar: Any = None
    # Free-form extras (attachment text, linked document body, ...) for
    # enrichers that need more than the component itself.
    extras: Dict[str, Any] = dc_field(default_factory=dict)

    @property
    def text(self):
        """Concatenated free text, which is what most enrichers actually read."""
        return '\n'.join(p for p in (self.summary, self.description,
                                     self.location, self.url) if p)


class Enricher:
    """Base class. Subclass, set ``name``/``version``/``fields``, override ``run``."""

    name = 'enricher'
    version = '0'
    fields: tuple = ()
    priority = 100          # lower runs first
    enabled_by_default = True

    def applies_to(self, ctx: EnrichmentContext) -> bool:
        return True

    def run(self, ctx: EnrichmentContext) -> Dict[str, DerivedValue]:
        raise NotImplementedError

    @property
    def model_id(self):
        return f'{self.name}/{self.version}'


REGISTRY: List[Enricher] = []


def register(cls):
    """Class decorator. Instantiates and adds to the registry."""
    instance = cls()
    REGISTRY.append(instance)
    REGISTRY.sort(key=lambda e: (e.priority, e.name))
    return cls


def registry_names():
    return [e.name for e in REGISTRY]


# ---------------------------------------------------------------------------
# Built-in enrichers
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r'(?:\best(?:imate)?[:=]?\s*|~|\[|\()\s*'
    r'(?:(?P<h>\d+(?:[.,]\d+)?)\s*(?:h|hr|hrs|hours?)\s*)?'
    r'(?:(?P<m>\d+)\s*(?:m|min|mins|minutes?)\b)?',
    re.IGNORECASE)


@register
class DurationEnricher(Enricher):
    """Pull an effort estimate out of shorthand: ``~45m``, ``[2h30]``, ``est: 1h``."""

    name = 'duration'
    version = '1'
    fields = ('estimate_minutes',)
    priority = 10

    def run(self, ctx):
        for match in _DURATION_RE.finditer(ctx.text):
            hours, minutes = match.group('h'), match.group('m')
            if not hours and not minutes:
                continue
            total = 0
            if hours:
                total += int(round(float(hours.replace(',', '.')) * 60))
            if minutes:
                total += int(minutes)
            if not 1 <= total <= 60 * 24:
                continue
            return {'estimate_minutes': DerivedValue(
                total, confidence=0.85, model=self.model_id,
                evidence=match.group(0).strip())}
        return {}


_ENERGY_HINTS = {
    'high': ('design', 'architect', 'write', 'draft', 'debug', 'diagnose',
             'negotiate', 'plan', 'review', 'research', 'interview'),
    'low': ('file', 'email', 'call', 'book', 'order', 'pay', 'renew', 'scan',
            'upload', 'tidy', 'archive', 'confirm', 'check', 'log'),
}


@register
class EnergyEnricher(Enricher):
    """Guess cognitive load from the verb. Deliberately low confidence."""

    name = 'energy'
    version = '1'
    fields = ('energy',)
    priority = 20

    def run(self, ctx):
        haystack = ctx.text.lower()
        for level, verbs in _ENERGY_HINTS.items():
            for verb in verbs:
                if re.search(rf'\b{verb}\w*\b', haystack):
                    return {'energy': DerivedValue(
                        level, confidence=0.45, model=self.model_id, evidence=verb)}
        return {}


_TAG_RE = re.compile(r'(?<![\w/])[@#]([a-z0-9][\w-]{1,31})', re.IGNORECASE)


@register
class ContextTagEnricher(Enricher):
    """Collect ``@garage`` / ``#mot`` style tags, plus iCalendar CATEGORIES."""

    name = 'context'
    version = '1'
    fields = ('contexts',)
    priority = 30

    def run(self, ctx):
        tags = {m.group(1).lower() for m in _TAG_RE.finditer(ctx.text)}
        tags.update(c.strip().lower() for c in (ctx.categories or []) if c.strip())
        if not tags:
            return {}
        return {'contexts': DerivedValue(
            sorted(tags), confidence=0.9, model=self.model_id,
            evidence=','.join(sorted(tags)))}


_URL_RE = re.compile(r'https?://[^\s<>"\')]+')
_TICKET_RE = re.compile(r'\b([A-Z][A-Z0-9]{1,9}-\d+)\b')
_MSGID_RE = re.compile(r'<([^<>@\s]+@[^<>@\s]+)>')
_SHA_RE = re.compile(r'\b([0-9a-f]{7,40})\b')

_HOST_SYSTEMS = (
    ('github.com', 'github'), ('gitlab.com', 'gitlab'),
    ('atlassian.net', 'jira'), ('linear.app', 'linear'),
    ('mail.google.com', 'gmail'), ('slack.com', 'slack'),
)


@register
class ProvenanceEnricher(Enricher):
    """Find the thing that spawned this item -- URL, ticket, commit, Message-ID.

    This is what closes the loop: a reminder that knows which email created it
    is a reminder you can act on without hunting."""

    name = 'provenance'
    version = '1'
    fields = ('source_url', 'source_ref', 'source_system')
    priority = 40

    def run(self, ctx):
        out = {}
        url = ctx.url or None
        match = _URL_RE.search(ctx.text)
        if match:
            url = url or match.group(0)
        if url:
            out['source_url'] = DerivedValue(
                url[:1000], confidence=0.9, model=self.model_id, evidence=url[:120])
            for host, system in _HOST_SYSTEMS:
                if host in url:
                    out['source_system'] = DerivedValue(
                        system, confidence=0.9, model=self.model_id, evidence=host)
                    break

        ticket = _TICKET_RE.search(ctx.summary) or _TICKET_RE.search(ctx.description)
        msgid = _MSGID_RE.search(ctx.description or '')
        if ticket:
            out['source_ref'] = DerivedValue(
                ticket.group(1), confidence=0.85, model=self.model_id,
                evidence=ticket.group(0))
        elif msgid:
            out['source_ref'] = DerivedValue(
                msgid.group(1), confidence=0.8, model=self.model_id,
                evidence=msgid.group(0))
            out.setdefault('source_system', DerivedValue(
                'email', confidence=0.6, model=self.model_id))
        return out


_BLOCKED_RE = re.compile(
    r'\b(?:blocked\s+by|waiting\s+on|depends\s+on|after)\b[:\s]+([^\n;.]{2,120})',
    re.IGNORECASE)
_BLOCKS_RE = re.compile(r'\b(?:blocks|unblocks|enables)\b[:\s]+([^\n;.]{2,120})',
                        re.IGNORECASE)


@register
class DependencyEnricher(Enricher):
    """Parse ``blocked by: ...`` prose and RELATED-TO into a dependency edge list.

    Values may be UIDs or free text; resolution to real UIDs happens later, in
    ``app.caldav.mapping``, where the collection is in scope."""

    name = 'dependency'
    version = '1'
    fields = ('blocked_by', 'blocks')
    priority = 50

    def run(self, ctx):
        out = {}
        blocked = [m.group(1).strip() for m in _BLOCKED_RE.finditer(ctx.text)]
        blocks = [m.group(1).strip() for m in _BLOCKS_RE.finditer(ctx.text)]
        if blocked:
            out['blocked_by'] = DerivedValue(
                blocked, confidence=0.6, model=self.model_id, evidence=blocked[0])
        if blocks:
            out['blocks'] = DerivedValue(
                blocks, confidence=0.6, model=self.model_id, evidence=blocks[0])
        return out


# ---------------------------------------------------------------------------
# Optional LLM enricher
# ---------------------------------------------------------------------------

_LLM_BACKEND = None


def set_llm_backend(fn):
    """Install the callable the LLM enricher delegates to.

    ``fn(prompt: str, ctx: EnrichmentContext) -> dict`` must return a mapping
    of ``{field: {"value": ..., "confidence": float, "evidence": str}}``.
    Keeping this an injected callable means the CalDAV layer has no opinion
    about which provider you use, no network calls in tests, and no API key
    handling in this module.
    """
    global _LLM_BACKEND
    _LLM_BACKEND = fn


# string.Template, not str.format: the prompt contains literal JSON braces and
# str.format would try to read them as replacement fields.
LLM_PROMPT = Template("""You extract structured task metadata from calendar items.
Return JSON only. Omit any field you are not confident about.

Allowed fields:
  estimate_minutes  integer, realistic working minutes
  energy            one of: low, medium, high
  contexts          list of short lowercase tags (place or tool required)
  blocked_by        list of prerequisites, verbatim from the text
  source_ref        ticket id, invoice number, or reference code

For each field emit {"value": ..., "confidence": 0.0-1.0, "evidence": "quoted span"}.

ITEM:
summary: $summary
description: $description
location: $location
categories: $categories
""")


@register
class LlmEnricher(Enricher):
    """Model-backed extraction for text the regexes cannot reach.

    Disabled unless a backend is installed via :func:`set_llm_backend` *and*
    the caller passes ``allow_llm=True``. Runs last and at lower priority than
    the rule-based enrichers, so a deterministic match always wins a tie.
    """

    name = 'llm'
    version = '1'
    fields = ('estimate_minutes', 'energy', 'contexts', 'blocked_by', 'source_ref')
    priority = 900
    enabled_by_default = False

    def applies_to(self, ctx):
        return _LLM_BACKEND is not None and bool(ctx.text.strip())

    def run(self, ctx):
        if _LLM_BACKEND is None:
            return {}
        prompt = LLM_PROMPT.substitute(
            summary=ctx.summary or '', description=ctx.description or '',
            location=ctx.location or '', categories=', '.join(ctx.categories or []))
        try:
            raw = _LLM_BACKEND(prompt, ctx) or {}
        except Exception as exc:  # never let enrichment break a CalDAV write
            logger.warning('LLM enricher failed for %s: %s', ctx.uid, exc)
            return {}

        out = {}
        for name, payload in raw.items():
            if isinstance(payload, dict):
                value = payload.get('value')
                confidence = float(payload.get('confidence', 0.5))
                evidence = payload.get('evidence')
            else:
                value, confidence, evidence = payload, 0.5, None
            if value in (None, '', [], {}):
                continue
            out[name] = DerivedValue(value, confidence=min(confidence, 0.95),
                                     model=self.model_id, evidence=evidence)
        return out


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(ctx: EnrichmentContext, allow_llm=False, only=None):
    """Run every applicable enricher; highest confidence wins per field."""
    winners: Dict[str, DerivedValue] = {}

    for enricher in REGISTRY:
        if only is not None and enricher.name not in only:
            continue
        if not enricher.enabled_by_default and not (allow_llm and enricher.name == 'llm'):
            continue
        if not enricher.applies_to(ctx):
            continue
        try:
            produced = enricher.run(ctx) or {}
        except Exception as exc:
            logger.warning('Enricher %r failed on %s: %s', enricher.name, ctx.uid, exc)
            continue
        for name, derived in produced.items():
            if not isinstance(derived, DerivedValue):
                derived = DerivedValue(derived)
            derived.source = enricher.name
            incumbent = winners.get(name)
            if incumbent is None or derived.confidence > incumbent.confidence:
                winners[name] = derived
    return winners


def apply_to_sidecar(sidecar, derived_map, digest=None):
    """Write pipeline output onto a sidecar row, honouring locks.

    Returns the list of fields actually changed, which is useful for logging
    and for deciding whether the collection's sync counter needs bumping.
    """
    changed = []
    sidecar.derived = dict(sidecar.derived or {})

    for name, derived in derived_map.items():
        if sidecar.is_locked(name):
            continue  # user owns this field

        sidecar.derived[name] = derived.as_meta()

        if name not in TYPED_FIELDS:
            changed.append(name)
            continue

        if name in LIST_FIELDS:
            existing = list(getattr(sidecar, name, None) or [])
            incoming = derived.value if isinstance(derived.value, (list, tuple)) else [derived.value]
            merged = sorted({str(v) for v in existing} | {str(v) for v in incoming})
            if merged != existing:
                setattr(sidecar, name, merged)
                changed.append(name)
        else:
            if getattr(sidecar, name, None) != derived.value:
                setattr(sidecar, name, derived.value)
                changed.append(name)

    if digest is not None:
        sidecar.enriched_digest = digest
    sidecar.enriched_at = datetime.utcnow()
    return changed
