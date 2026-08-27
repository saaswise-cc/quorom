"""End-to-end over the two legs a session can actually reach: the product
database and the artifact. Salesforce and HubSpot are deliberately absent."""

from __future__ import annotations

import json

import psycopg
import pytest
import requests
from openpyxl import load_workbook

from quorom import db
from quorom.config import Config
from quorom.gong.importer import import_range
from quorom.weekly.run import run_weekly

ACCOUNT = "northwind.com"


def _seed_account(dsn: str) -> str:
    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute(
            "insert into accounts (name, internal_domains) values (%s, %s) returning id",
            (ACCOUNT, ["northwind.com"]),
        ).fetchone()
    return str(row[0])


def _cfg(dsn: str, tmp_path, **overrides) -> Config:
    kwargs = dict(
        database_url=dsn,
        account=ACCOUNT,
        week_start="2026-08-17",
        output_dir=str(tmp_path),
    )
    kwargs.update(overrides)
    return Config(**kwargs)


def _import(dsn: str, account_id: str, gong_calls, database_conn=None):
    from tests.conftest import FakeGong

    with psycopg.connect(dsn) as conn:
        result = import_range(
            conn, FakeGong(gong_calls), account_id, ["northwind.com"],
            "2025-10-01", "2026-08-24", log=lambda *_: None,
        )
        conn.commit()
    return result


def test_import_classifies_and_resolves(database, gong_calls):
    account_id = _seed_account(database)
    result = _import(database, account_id, gong_calls)

    assert result.meetings_upserted == 3

    with psycopg.connect(database) as conn:
        kinds = dict(
            conn.execute(
                "select coalesce(domain_kind, '<null>'), count(*) from attendees "
                "group by 1"
            ).fetchall()
        )
        # Gong's affiliation wins where present; domain classification fills the
        # rest. The party with neither name nor email is not a person.
        assert kinds["internal"] == 2
        assert kinds["personal"] == 1          # sam@gmail.com
        assert kinds["<null>"] == 1            # named, no email, no affiliation
        assert kinds["external"] == 12         # Dana x2, support@, 9 trainees

        # Internal attendees never become people.
        emails = {
            r[0]
            for r in conn.execute(
                "select email from people where email is not null"
            ).fetchall()
        }
        assert "sam@northwind.com" not in emails
        assert {"dana.reyes@acme.com", "d.reyes@acme.com"} <= emails

        # The name-only attendee gets an unmatched person of its own.
        assert conn.execute(
            "select count(*) from people where unmatched"
        ).fetchone()[0] == 1


def test_import_times_the_run_it_just_did(database, gong_calls):
    """Counts alone cannot answer 'what would a year cost?'. The elapsed time
    is measured around the real work, not assembled by the caller."""
    account_id = _seed_account(database)
    result = _import(database, account_id, gong_calls)

    assert result.elapsed_seconds > 0
    assert str(result).endswith("elapsed")


def test_reimport_is_idempotent(database, gong_calls):
    """The failure this guards: an importer that inserts person_attendees with no uniqueness
    constraint. 0002 adds one, so a second run over an overlapping range would
    raise instead of doing nothing — a backfill that looks fine, then breaks the
    overnight job the next day."""
    account_id = _seed_account(database)
    first = _import(database, account_id, gong_calls)

    def counts() -> tuple:
        with psycopg.connect(database) as conn:
            return tuple(
                conn.execute(f"select count(*) from {t}").fetchone()[0]
                for t in ("meetings", "attendees", "people", "person_attendees",
                          "person_identifiers")
            )

    before = counts()
    second = _import(database, account_id, gong_calls)
    assert counts() == before
    assert second.calls_already_imported == 3
    assert second.attendees_created == 0
    assert first.meetings_upserted == second.meetings_upserted


def test_weekly_runs_without_a_crm(database, gong_calls, tmp_path):
    """No Salesforce, no HubSpot. The run must still produce the artifact, with
    the missing legs stated rather than silently absent."""
    account_id = _seed_account(database)
    _import(database, account_id, gong_calls)

    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(
            "insert into user_focus_profiles (account_id, version_number, is_active, "
            "profile_data) values (%s, 1, true, %s)",
            (account_id, json.dumps({
                "employee_count_min": 200, "employee_count_max": 10000,
                "hq_geographies": ["North America"],
                "focus_seniority": ["c-level", "vp", "director"],
            })),
        )

    cfg = _cfg(database, tmp_path)
    paths = run_weekly(cfg, log=lambda *_: None)

    wb = load_workbook(paths["xlsx"])
    assert wb.sheetnames == [
        "1 - Met this week",
        "2 - Missing from CRM",
        "3 - Company coverage",
        "4 - Stakeholder list",
    ]

    # 11 distinct external people met in the pinned week: Dana, support@, and
    # nine trainees. The historical call and the internal attendees are out.
    met = list(wb["1 - Met this week"].iter_rows(min_row=2, values_only=True))
    assert len(met) == 11

    # With no CRM configured every row is "not checked" — never "NO".
    missing = [
        r for r in wb["2 - Missing from CRM"].iter_rows(min_row=2, values_only=True)
        if r[0]
    ]
    assert missing == []

    dump = json.loads(open(paths["json"]).read())
    assert dump["account"] == ACCOUNT
    assert dump["focus_profile"]["employee_count_min"] == 200

    html = open(paths["html"]).read()
    assert "northwind.com" in html     # the account, not a hardcoded name
    assert "not for publishing" in html


def test_history_splits_on_a_changed_address(database, gong_calls):
    """The defect that justifies the identity tables, as a test rather than a
    claim: Dana attended under two addresses, so the email-keyed history query
    reports her as two people with two different last_met dates."""
    account_id = _seed_account(database)
    _import(database, account_id, gong_calls)

    cfg = Config(database_url=database, account=ACCOUNT, week_start="2026-08-17")
    with psycopg.connect(database) as conn:
        history = db.met_history(conn, cfg, ["acme.com"])

        assert history["dana.reyes@acme.com"]["last_met"].isoformat() == "2026-08-18"
        assert history["d.reyes@acme.com"]["last_met"].isoformat() == "2025-10-21"

        # person_identifiers already holds what would collapse them.
        rows = conn.execute(
            "select count(distinct person_id) from person_identifiers "
            "where email in ('dana.reyes@acme.com', 'd.reyes@acme.com')"
        ).fetchone()[0]
    # Two records today because the addresses were never linked; the read path
    # that fixes this is the one described in migrations/0002_identity.sql.
    assert rows == 2


def test_group_call_is_labelled_not_judged(database, gong_calls):
    account_id = _seed_account(database)
    _import(database, account_id, gong_calls)

    cfg = Config(database_url=database, account=ACCOUNT, week_start="2026-08-17")
    with psycopg.connect(database) as conn:
        history = db.met_history(conn, cfg, ["acme.com"])

    from quorom.weekly.stakeholders import recent_contact

    trainee = history["trainee1@acme.com"]
    assert trainee["smallest_meeting"] == 9      # above GROUP_CALL_MIN of 8
    # Recency is computed against today, so assert the label rather than the date.
    label = recent_contact(cfg, trainee, None)
    assert "group call, 9 attendees" in label or label.startswith("no —")


@pytest.mark.parametrize(
    "title, rank",
    [
        ("Chief Revenue Officer", 3),
        ("Vice President, Sales", 2),   # must not match on 'president'
        ("SVP Marketing", 2),
        ("Chief of Staff", 2),          # not C-level here
        ("Director of RevOps", 1),
        ("", 0),
    ],
)
def test_seniority_ordering(title, rank):
    from quorom.weekly.stakeholders import seniority_rank

    assert seniority_rank(title) == rank


def test_soql_quoting():
    from quorom.crm.salesforce import soql_quote

    assert soql_quote("o'brien@acme.com") == "o\\'brien@acme.com"
    assert soql_quote("a\\b") == "a\\\\b"


# --- HubSpot 429 handling ---------------------------------------------------- #
#
# The search endpoint is burst-limited, so a weekly run has to wait one out
# rather than die. No network: requests.post is replaced with a scripted
# sequence of responses, and the sleep is recorded instead of taken.


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


@pytest.fixture
def hubspot_calls(monkeypatch):
    """Script HubSpot's replies; return the recorded sleeps and request count."""
    from quorom.crm import hubspot as hs_mod

    state = {"sent": [], "slept": []}

    def install(responses):
        queue = list(responses)

        def fake_post(url, **kwargs):
            state["sent"].append(kwargs.get("json"))
            return queue.pop(0)

        monkeypatch.setattr(hs_mod.requests, "post", fake_post)
        monkeypatch.setattr(hs_mod.time, "sleep", lambda s: state["slept"].append(s))
        return state

    return install


def _client():
    """A client with a fake key, built without touching Config().

    Config() calls load_dotenv(), so constructing one here would pull the real
    HubSpot key out of .env and put it in any failure output.
    """
    from types import SimpleNamespace

    from quorom.config import HubSpotConfig
    from quorom.crm.hubspot import HubSpot

    return HubSpot(SimpleNamespace(hubspot=HubSpotConfig(api_key="test-key")))


def test_hubspot_retries_a_429_then_succeeds(hubspot_calls):
    hit = {"results": [{"id": "1", "properties": {"email": "a@acme.com"}}]}
    state = hubspot_calls([_Resp(429), _Resp(200, hit)])

    got = _client().contact_by_email("a@acme.com")

    assert got.email == "a@acme.com"             # the run continues
    assert len(state["sent"]) == 2               # it retried exactly once
    assert state["slept"] == [2.0]               # backed off before retrying


def test_hubspot_honours_retry_after(hubspot_calls):
    state = hubspot_calls(
        [_Resp(429, headers={"Retry-After": "7"}), _Resp(200, {"total": 4})]
    )

    assert _client().count_domain("acme.com") == 4
    assert state["slept"] == [7.0]               # HubSpot's number, not ours


def test_hubspot_caps_a_huge_retry_after(hubspot_calls):
    from quorom.crm.hubspot import MAX_BACKOFF

    state = hubspot_calls(
        [_Resp(429, headers={"Retry-After": "86400"}), _Resp(200, {"total": 0})]
    )

    _client().count_domain("acme.com")
    assert state["slept"] == [MAX_BACKOFF]        # bounded, so it cannot hang


def test_hubspot_gives_up_loudly_when_throttling_persists(hubspot_calls):
    from quorom.crm.hubspot import HubSpotRateLimited, MAX_ATTEMPTS

    state = hubspot_calls([_Resp(429)] * MAX_ATTEMPTS)

    with pytest.raises(HubSpotRateLimited):
        _client().contact_by_email("a@acme.com")

    assert len(state["sent"]) == MAX_ATTEMPTS     # capped, not unbounded
    assert len(state["slept"]) == MAX_ATTEMPTS - 1  # no sleep after the last try


def test_hubspot_does_not_retry_other_errors(hubspot_calls):
    state = hubspot_calls([_Resp(500)])

    with pytest.raises(requests.HTTPError):
        _client().contact_by_email("a@acme.com")

    assert len(state["sent"]) == 1                # 500 still fails immediately
