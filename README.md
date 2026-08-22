# ESA Scout

Monitors European Space Agency opportunities, scores each one against **your**
background using an LLM, alerts you when something becomes actionable, and
renders it all on a dashboard you can deploy to Vercel.

It watches three opportunity sources:

| Source | What it covers |
| --- | --- |
| [ESA Academy Training & Learning Programme](https://educationforms.esa.int/tlp/table/current-opportunities/) | Training courses, workshops, conference sponsorships |
| [ESA Academy opportunities](https://www.esa.int/Education/ESA_Academy/ESA_Academy_opportunities3) | REXUS/BEXUS, Fly Your Satellite!, Experiments Programme |
| [jobs.esa.int](https://jobs.esa.int) | Internships, Young Graduate Trainee and student vacancies |

…plus a second surface for the opportunities nobody advertises:

| Source | What it covers |
| --- | --- |
| [ESA-star public entity directory](https://esastar-emr.sso.esa.int/PublicEntityDir/PublicEntityDirSme) | ESA-registered space SMEs in Spain and Italy, ranked as **speculative internship targets** |

---

## How it works

```
                  ┌──────────────┐
   ESA sources ──▶│   scraper    │──┐
                  └──────────────┘  │
                                    ▼
CV.pdf + GitHub ─▶ profile_parser ─▶ evaluator ─▶ state_manager ─▶ data/opportunities.json
                                        │              │                     │
                                     (LLM)             ▼                     ▼
                                                    notifier            Next.js dashboard
                                              email / Telegram / Discord     (Vercel)
```

1. **Scrape.** Each source is parsed independently; one failing source degrades
   the run instead of ending it.
2. **Profile.** Your CV PDF is parsed for education, skills and projects, and
   your public GitHub repositories are fetched for current, demonstrated skills.
3. **Evaluate.** Every opportunity is scored 0–100 with a justification, the
   skills it requires, your gaps, and a preparation checklist specific to you.
4. **Diff.** The new results are compared against the previous run to find
   status changes and newly listed opportunities.
5. **Notify.** Alerts fire *only* on a status change or a new open opportunity
   scoring above your threshold.
6. **Publish.** The snapshot is written to `data/opportunities.json`, committed
   by CI, and rendered by the dashboard.

---

## Quick start

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure (every value is optional — see the notes below)
cp .env.example .env

# 3. Put your CV in the repo root (or agent/profile/) as a PDF, then check it parsed
python -m agent.main profile

# 4. Run the pipeline
python -m agent.main run

# 5. View the dashboard
cd web && npm install && npm run dev   # http://localhost:3000
```

**It works with an empty `.env`.** Without `LLM_API_KEY` you still get every
opportunity, categorised, with deadline tracking — just no AI scores. Without
notification credentials, changes are recorded but nothing is sent.

### CLI

```bash
python -m agent.main run              # full pipeline (default)
python -m agent.main run --no-notify  # everything except sending alerts
python -m agent.main scrape           # scrape only — verify selectors after an ESA redesign
python -m agent.main profile          # show what was parsed from your CV and GitHub
python -m agent.main notify --test    # send a sample alert to check your channels
python -m agent.main -v run           # debug logging

python -m agent.main sme              # scan ESA-star SMEs (no LLM calls)
python -m agent.main sme --evaluate   # scan and rank them for an internship
python -m agent.main sme --evaluate --limit 5   # cap the LLM calls while testing
```

Exit codes: `0` success · `1` failure · `2` completed with warnings (for
example, one source was unreachable).

---

## Configuration

All configuration is environment variables; see [`.env.example`](.env.example)
for the annotated list. The essentials:

| Variable | Purpose |
| --- | --- |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Any OpenAI-compatible endpoint — xAI/Grok (default), OpenRouter, Groq, OpenAI, or a local server |
| `GITHUB_USERNAME` | Your public GitHub, used to judge current skills |
| `RESEND_API_KEY` **or** `SMTP_*` | Email delivery |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram alerts |
| `DISCORD_WEBHOOK_URL` | Discord alerts |
| `NOTIFY_MATCH_THRESHOLD` | Minimum score for a new open opportunity to alert (default 70) |
| `HIGH_FIT_THRESHOLD` | Score counted as "high fit" on the dashboard (default 80) |
| `SME_COUNTRIES`, `SME_KEYWORDS`, `SME_TARGET_TERM` | What the SME matcher scans and what it optimises for |
| `SME_MAX_EVALUATIONS` | Cost cap on SME ranking per run (default 40) |

### When do notifications fire?

Only when something genuinely changed:

- an opportunity's **status changed** (`Pending → Open`), or
- a **newly listed, open** opportunity scores **≥ `NOTIFY_MATCH_THRESHOLD`**.

Newly listed low scorers and approaching deadlines appear on the dashboard but
do not alert. **The first run never notifies** — with no prior state everything
looks new, and an alert storm on setup teaches you to ignore alerts.

---

## SME Internship Matcher (Spain & Italy)

ESA Academy calls are advertised and competitive. The 600-odd SMEs in ESA's
supplier directory are neither — most have never posted an internship, which is
precisely why a well-aimed cold email works. This feature finds the ones worth
writing to.

```bash
python -m agent.main sme --evaluate
```

Then open **`/sme`** on the dashboard.

**What it does.** It walks the ESA-star public entity directory filtered to
Spain and Italy, opens each company's detail record for its city, website and
English description, keeps only those whose text matches the relevance taxonomy
(`SME_KEYWORDS`), and asks the LLM to score each survivor 0–100 as a speculative
internship target — with a two-sentence rationale, a role to propose, focus
areas to emphasise, and outreach tips specific to that company.

A full scan is ~620 companies in under a minute; ranking is capped by
`SME_MAX_EVALUATIONS` and, like the opportunity evaluator, cached by
fingerprint, so a re-scan only pays for companies whose description changed.

**Domain tags are derived, not published.** ESA-star exposes no structured
activity field — only free text. The tags on each card come from word-boundary
keyword matching against that text, which is why the UI describes them as
inferred. Word boundaries matter: a substring match makes `GIS` hit "logistics"
and "registration".

**Without an LLM key** the scan still runs and the page still works — you get
the filtered company list with domain tags and an explicit banner saying the
ranking has not run. The **Analyze best SME matches** button declines with a
clear notice rather than silently producing an unranked scan.

> To drive that button from `npm run dev`, put the key in `web/.env.local` —
> Next.js loads env files from the app directory, not the repository root. The
> route then spawns the agent locally; set `PYTHON_BIN=../.venv/bin/python` if
> your interpreter is not on `PATH` as `python3`. In production it dispatches
> the GitHub workflow instead.

---

## Deploying

### Dashboard on Vercel

1. Push this repository to GitHub.
2. Import it at [vercel.com/new](https://vercel.com/new).
3. **Set the project's Root Directory to `web`.** This is the only required
   setting — the framework, build command and output directory are detected.
4. Deploy.

The dashboard reads `web/public/data/opportunities.json`, which the agent writes
alongside the canonical `data/opportunities.json` on every run. Only files
inside the Next.js project are guaranteed to ship in a Vercel deployment, which
is why the mirror exists.

To enable the dashboard's **Sync now** button, add these Vercel environment
variables:

| Variable | Value |
| --- | --- |
| `GITHUB_REPO` | `your-user/esa-scout` |
| `GITHUB_DISPATCH_TOKEN` | a fine-grained PAT with `actions: write` |
| `SYNC_SECRET` | optional; when set, callers must send an `x-sync-secret` header |
| `GITHUB_SME_WORKFLOW` | optional; workflow for the SME scan button (default `sme.yml`) |
| `LLM_API_KEY` | optional; its presence lets the SME scan button explain itself before spending a run |

Without them the buttons report that remote sync is not configured; everything
else works.

### Scheduled runs on GitHub Actions

[`.github/workflows/cron.yml`](.github/workflows/cron.yml) runs every 12 hours.
It installs dependencies, **runs the test suite** (so an ESA markup change fails
loudly rather than silently committing an empty dashboard), runs the agent,
commits the updated data and dispatches notifications.

Add your credentials under **Settings → Secrets and variables → Actions**:

- **Secrets:** `LLM_API_KEY`, `RESEND_API_KEY`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, `SMTP_*`
- **Variables:** `LLM_BASE_URL`, `LLM_MODEL`, `GH_USERNAME`, `EMAIL_FROM`,
  `EMAIL_TO`, `DASHBOARD_URL`

> `GH_USERNAME` is a variable rather than `GITHUB_USERNAME` because GitHub
> reserves the `GITHUB_` prefix for its own variables. The workflow maps it to
> `GITHUB_USERNAME` for the agent.

[`.github/workflows/sme.yml`](.github/workflows/sme.yml) does the same for the
SME matcher, weekly rather than twice daily: the supplier directory changes far
more slowly than the opportunity calendar, and each scan costs ~600 requests to
a public ESA service plus LLM calls. It also backs the dashboard's **Analyze
best SME matches** button via `workflow_dispatch`. Add `SME_*` under
**Variables** if you want to override the defaults.

Committing a data file triggers a Vercel redeploy, so the dashboard refreshes
automatically.

---

## Project layout

```
esa-scout/
├── agent/
│   ├── main.py            # CLI entry point, orchestrates the pipeline
│   ├── scraper.py         # runs each source, merges and dedupes
│   ├── sources/           # one parser per source
│   │   ├── tlp.py         #   Training & Learning Programme table
│   │   ├── academy.py     #   Projects & Testing programmes
│   │   ├── jobs.py        #   SuccessFactors careers portal
│   │   └── sme_matcher.py #   ESA-star SME directory (GridMvc + detail popups)
│   ├── profile_parser.py  # CV PDF extraction + GitHub API
│   ├── evaluator.py       # LLM scoring, with fingerprint-based caching
│   ├── sme_evaluator.py   # LLM ranking of SMEs as internship targets
│   ├── state_manager.py   # persistence + change detection for opportunities
│   ├── sme_state.py       # persistence for SME matches
│   ├── storage.py         # atomic JSON writes shared by both state files
│   ├── notifier.py        # Resend / SMTP / Telegram / Discord dispatch
│   ├── render.py          # message bodies for each channel
│   ├── dates.py           # ESA's free-text date parsing
│   ├── categorize.py      # keyword classification
│   ├── html.py            # Scrapling Selector with a BeautifulSoup fallback
│   ├── fetcher.py         # retrying HTTP client
│   ├── models.py          # frozen dataclasses + the JSON contract
│   ├── sme_models.py      # the same, for SME matches
│   └── config.py          # all environment configuration
├── data/
│   ├── opportunities.json     # canonical opportunity output (committed)
│   └── sme_matches.json       # canonical SME output (committed)
├── web/                       # Next.js 16 dashboard
│   ├── app/                   # App Router pages and API routes
│   │   ├── page.tsx           #   / — opportunities
│   │   ├── sme/page.tsx       #   /sme — SME internship targets
│   │   └── api/               #   opportunities, sme, sync, sync/sme/scan
│   ├── components/            # headers, filter bars, cards, drawers
│   ├── lib/                   # types, data loading, filtering, formatting
│   └── public/data/           # deployed mirrors of both snapshots
├── tests/                     # pytest suite + real captured fixtures
└── .github/workflows/         # cron.yml (12-hourly) · sme.yml (weekly)
```

---

## Testing

```bash
# Backend — 354 tests
python -m pytest tests/ -q
python -m pytest tests/ --cov=agent --cov-report=term-missing   # 87% coverage

# Frontend — 101 tests
cd web && npm test && npm run typecheck
```

The parser tests run against **real ESA HTML and ESA-star JSON** captured in
`tests/fixtures/`.
That is deliberate: if ESA changes its markup, those tests fail and tell you
which selector broke, rather than the scraper quietly returning nothing. The CI
workflow runs them before every scouting run for exactly that reason.

---

## Design notes

A few decisions that are not obvious from the code:

**ESA's declared status wins over an elapsed deadline.** Many TLP rows are
labelled `Open` with a deadline that has already passed, and some deadlines are
published without a year (`19 April`). Silently reclassifying those as `Closed`
risks hiding a genuinely open call, which costs far more than showing a stale
one. The dashboard flags an elapsed deadline separately, computed in the browser
so it is never stale between runs. The careers portal is the exception: its
closing dates are system-generated and authoritative, so they *do* drive status.

**Evaluations are cached by fingerprint.** Each result stores a hash of
(opportunity content + profile + model). An unchanged opportunity reuses its
score, so a twice-daily cron normally pays for only what actually changed. Edit
your CV and everything is re-scored automatically, because the profile hash
changes.

**Scrapling parses; httpx fetches.** Scrapling's `Selector` provides adaptive,
self-healing selectors, but its browser-backed fetchers pull in Playwright and
`curl_cffi` — heavy and flaky in CI, and unnecessary because all three ESA
sources are server-rendered. Set `SCRAPLING_FETCHER=1` (and install the optional
extras) if ESA ever adds JavaScript rendering or bot protection.

**Columns are located by header label, not index.** The TLP table contains
empty spacer cells; matching on the header text means an added or reordered
column cannot silently shift every field into the wrong place.

**Nothing raises on bad input.** A missing CV, an unreachable GitHub, a failed
LLM call and a corrupt state file all degrade to a warning carried in the
snapshot and shown on the dashboard. A total scrape failure is the one case that
aborts *without writing*, so a bad run can never blank a working dashboard.

---

## Troubleshooting

**"No opportunities scraped from any source"** — ESA changed its markup. Run
`python -m pytest tests/test_sources.py -q` to see which parser broke, then
`python -m agent.main -v scrape` to inspect live output.

**Match scores are all 0** — `LLM_API_KEY` is unset, or the provider rejected
the request. Run with `-v` to see the error; it is also recorded in the
snapshot's `errors` and shown on the dashboard.

**No notifications** — remember the first run is always silent. Verify your
channels with `python -m agent.main notify --test`, and use
`NOTIFY_DRY_RUN=true` to print messages instead of sending them.

**The SME list is empty or tiny** — ESA-star answers its grid endpoint with
JSON only for requests carrying `X-Requested-With: XMLHttpRequest`; without it
you get the page shell and zero rows. Run
`python -m pytest tests/test_sme_matcher.py -q` to confirm the parser, then
`python -m agent.main -v sme` to watch the live requests. A very small match
count usually means `SME_KEYWORDS` was narrowed rather than that the scan failed.

**CV parsed badly** — check with `python -m agent.main profile`. Both pdfplumber
and pypdf are tried and the cleaner extraction wins; if a heavily designed CV
still parses poorly, a simpler text-based PDF export works best.
