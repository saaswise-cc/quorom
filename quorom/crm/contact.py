"""One person, as the pipeline reads them — whatever CRM they came from.

The field map made Salesforce's *custom* field names portable and left
the *standard* ones hardcoded one module further out: `weekly/people.py` read
`Title` and `MobilePhone`, `weekly/stakeholders.py` read `Name`, `Email` and
`LastActivityDate`. So `crm/salesforce.py` genuinely contained no `__c` and the
test asserting that was honest, while a second CRM would still have broken every
caller.

This is the other half. An adapter hands back `Contact`, and nothing under
`weekly/` knows what any CRM calls anything.

Six fields, each one read by a column:

  name           tab 4 'Name'
  title          tab 1 'Title (SF)', tab 4 'Title', and the seniority ordering
  email          the key meeting history is joined on
  mobile         tab 1 and tab 4 'Mobile in CRM?' — presence only. The number
                 itself never leaves the CRM: sensitive contact fields pass
                 through to it and never into a Quorom store.
  linkedin       tab 1 'LinkedIn?' and tab 4 'LinkedIn'
  last_activity  one of the two sources behind tab 4 'Recent contact?'

`linkedin` is three-valued on purpose, and it is the reason this is not simply a
dict of strings:

  "https://…"  a URL on file
  ""           this CRM has the field; this person has nothing in it
  None         this CRM has no such field at all

Only the third means "not available in this CRM", and collapsing it into the
second is exactly the conflation the field map exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Contact:
    name: str = ""
    title: str = ""
    email: str = ""
    mobile: bool = False
    linkedin: Optional[str] = None
    last_activity: str = ""

    # The CRM's own record, with any sensitive field already reduced by the
    # adapter that built it. Opaque above this layer: it exists so the JSON dump
    # can carry what was actually read — which is what lets the ranking be
    # re-tuned without re-querying the CRM — and is never interpreted by
    # `weekly/`. Reading a field name out of this would put the coupling back.
    provenance: dict = field(default_factory=dict)
