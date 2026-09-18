# Deploying the runner on a PaaS (worked example)

Section 13 of `setup.md` asks you to decide what runs the scheduled job, and
points you toward whatever platform already runs alongside your database. For a
lot of teams that's a PaaS — Coolify (self-hosted), Railway, and Render are
three common ones, and what follows uses them as concrete examples, not a
recommendation of one over another.

**Platform behaviour described here was checked on 2026-09-11.** These are
other people's products and they change; if something below does not match what
you see, your platform's own documentation is right and this file is stale.

## The one decision that determines everything else: does your job stay running, or exit?

PaaS platforms handle scheduled work in one of two shapes, and they are
opposites:

- **Exec into a persistent container.** The platform expects something to
  already be running, and a scheduled task runs a command inside it.
  **Coolify's Scheduled Tasks work this way.** If your image has no long-lived
  process — a CLI tool with nothing to serve — it needs one anyway, just to
  give the platform something to exec into:
  ```dockerfile
  CMD ["tail", "-f", "/dev/null"]
  ```
- **Start an ephemeral job that's expected to exit.** The platform starts a
  fresh instance on schedule, runs your command, and tears it down when the
  command exits. **Railway's Cron Jobs and Render's Cron Jobs both work this
  way** — and both actively guard against a job that doesn't exit on its own:
  Railway skips the next run if the previous one is still going; Render caps a
  run at 12 hours and guarantees at most one active run of a given job. A
  keep-alive `CMD` here doesn't help — it's actively the wrong shape, and would
  either never let the platform consider the job "finished" or get killed by
  the platform's own timeout.

Check which model your platform uses before writing the Dockerfile's `CMD` —
guessing wrong produces two very different, both confusing failures: a
Scheduled Task with nothing to exec into (model 1's failure, if you built for
model 2), or a job that never finishes and gets killed or skipped by the
platform (model 2's failure, if you built for model 1).

## Triggering a deploy from CI

This section matters mainly if you're gluing an external CI system (GitLab CI,
GitHub Actions) to a self-hosted platform like Coolify. Platforms with their
own native git integration (Railway, Render) generally deploy on push without a
separate triggering step — check whether yours already does this before
building the pattern below.

Coolify exposes a deploy API. A CI job can trigger a deployment by POSTing to
it with the resource's UUID and a bearer token, then polling until the
deployment finishes:

```bash
curl -s -X POST "http://<coolify-host>:8000/api/v1/deploy" \
  -H "Authorization: Bearer ${COOLIFY_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"uuid": "<your-resource-uuid>", "environment": "production"}'
```

Two things that cost time on one real deployment, both silent rather than loud:

- **A placeholder left in the resource UUID fails the deploy every time**, with
  nothing pointing at that as the cause — the request goes through, gets a
  response, and the job still fails. If a deploy step has ever failed
  consistently since it was set up, check this first.
- **SSH may not be reachable from the platform's host at all**, which breaks
  the "Private Repository (Deploy Key)" method some UIs default you toward. If
  so, use an HTTPS remote with a token instead
  (`https://oauth2:<token>@your-git-host/...`) as the Git source.
  - If your Git host restricts **Project Access Token** creation at the
    group/org level, check whether that policy actually covers **Personal
    Access Tokens** too before assuming you're blocked — on GitLab, it does
    not: PATs are self-service even when Project Access Tokens are locked down
    centrally. A fine-grained PAT scoped to read-only access on the one project
    is enough for this.

## Scheduled tasks, either model

Map section 13's two jobs to whichever primitive your platform uses — a Coolify
Scheduled Task exec'ing into the persistent container, or a Railway/Render cron
service running each command to completion.

**Then check what your platform's alerting actually covers.** This is the part
most likely to be assumed rather than verified: a platform's built-in
monitoring commonly reports whether the container or service is *healthy*, not
whether an individual scheduled run *exited non-zero*. A weekly job that fails
every week can leave every dashboard green — and a weekly job that stops being
triggered at all exits nothing for your platform to notice.

**Section 13's "Making a failed run visible" is what to build**: check that
`last_run.json` carries the week you expected, rather than routing an exit code.
Read it before writing anything here, including its note on `OUTPUT_DIR`, which
in this document's second model does not survive the run.

## Postgres on a shared instance

If your database is a schema on a Postgres instance shared with other
applications rather than a dedicated one, **setup.md §8 covers this** — the
role, the grants, and why `search_path` must be set on the role rather than
passed in the connection string. Don't re-derive it from here; the section
explains the failure mode, which is that a pooler can drop the parameter and
nothing distinguishes that from working.

The one addition for a PaaS specifically: the same applies to a connection
string the platform generates for you. If your platform injects a
`DATABASE_URL` and offers somewhere to append parameters to it, that is still
the connection-string route, and still the one that fails silently under
pooling.

## If you store runs yourself

Most deployments should not. `RETAIN_RUNS` and migration `0005_run_outputs.sql`
(setup.md §14, Option A) do this for you, in one transaction, append-only by
privilege rather than by good intentions.

If you have written your own storage anyway — a table of your own, a row per
run — **put a uniqueness constraint on whatever identifies the run, and use
`INSERT … ON CONFLICT … DO UPDATE` rather than a plain `INSERT`.** A retried run
or a deliberate re-run of the same period will otherwise insert a second row
that looks exactly like the first, with nothing to catch it. Re-running is a
normal thing to do here — importing is idempotent by design, so nothing else in
the pipeline discourages it — which makes your storage the one place that
notices, or doesn't.

**And grant `UPDATE` when you do.** Postgres requires the `UPDATE` privilege for
the conflict clause specifically, separately from `INSERT` — so a role granted
`INSERT, SELECT`, which is what §14 tells you to grant, fails on
`ON CONFLICT … DO UPDATE` with a bare `permission denied`. The error names the
table, not the clause, and it arrives at the end of a run after all the work is
done. One real deployment lost a run to exactly this.

**It is a trade, not a detail.** §14 grants `INSERT, SELECT` and withholds
`UPDATE` deliberately: that is what makes the history append-only by privilege
rather than by good intentions, and it is why the pipeline's own retention uses
a plain `INSERT` and treats a re-run as a second row that really happened.
Adding `UPDATE` so a re-run overwrites in place is a reasonable choice — it is
just a different one, and worth making on purpose. Withhold `DELETE` either way.
