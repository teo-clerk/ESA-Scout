"""ESA Scout CLI — orchestrates the full scouting pipeline.

    python -m agent.main run              # scrape, evaluate, diff, notify, save
    python -m agent.main run --no-notify  # everything except sending
    python -m agent.main scrape           # scrape only, print a summary
    python -m agent.main profile          # show the parsed CV + GitHub profile
    python -m agent.main notify --test    # send a sample alert to verify wiring
    python -m agent.main sme --evaluate   # scan ESA-star SMEs and rank them
    python -m agent.main export           # write OPPORTUNITIES.md and SME_TARGETS.md

Exit codes: 0 success, 1 pipeline failure, 2 completed with degraded sources.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from . import (
    dates,
    evaluator,
    exporter,
    notifier,
    profile_parser,
    scraper,
    sme_evaluator,
    sme_state,
    state_manager,
)
from .config import REPO_ROOT, Settings, SmeSettings
from .fetcher import Fetcher
from .models import ChangeEvent, Opportunity, Profile, Snapshot
from .sme_models import SmeSnapshot
from .sources import sme_matcher

LOGGER = logging.getLogger("esa_scout")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_DEGRADED = 2


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # httpx logs every request at INFO, which drowns the pipeline's own output.
    logging.getLogger("httpx").setLevel(logging.WARNING)


# --- Commands --------------------------------------------------------------
def command_run(args: argparse.Namespace, settings: Settings) -> int:
    """The full pipeline: scrape -> profile -> evaluate -> diff -> notify -> save."""
    previous = state_manager.load_snapshot(settings.data_file)
    first_run = state_manager.is_first_run(previous)
    if first_run:
        LOGGER.info("no previous state — notifications suppressed for this run")

    LOGGER.info("scraping ESA sources")
    scrape_result = scraper.scrape_all(settings)
    errors = list(scrape_result.errors)

    if not scrape_result.opportunities:
        LOGGER.error("no opportunities scraped from any source — aborting without write")
        for error in errors:
            LOGGER.error("  %s", error)
        return EXIT_FAILURE

    LOGGER.info("building profile from CV and GitHub")
    profile = profile_parser.build_profile(settings)
    if profile.error:
        errors.append(f"profile: {profile.error}")
    if profile.github.error:
        errors.append(f"github: {profile.github.error}")

    evaluated, evaluation_errors = evaluator.evaluate_all(
        scrape_result.opportunities,
        profile,
        settings.llm,
        previous=previous.opportunities,
    )
    errors.extend(evaluation_errors)

    # Keep prior scores if this run could not produce one.
    evaluated = state_manager.merge_evaluations(evaluated, previous.opportunities)
    stamped = state_manager.carry_forward(evaluated, previous.opportunities)
    ordered = state_manager.sort_for_display(stamped)

    events = state_manager.diff(
        previous.opportunities, ordered, notify_threshold=settings.notify_threshold
    )
    _log_events(events)

    snapshot = state_manager.build_snapshot(
        opportunities=ordered, profile=profile, events=events, errors=errors
    )
    state_manager.save_snapshot(
        settings.data_file, snapshot, settings.high_fit_threshold
    )
    if settings.mirror_file is not None:
        # A mirror failure must not fail the run — the canonical file is written.
        try:
            state_manager.save_snapshot(
                settings.mirror_file, snapshot, settings.high_fit_threshold
            )
        except OSError as exc:
            LOGGER.warning("could not mirror data to %s: %s", settings.mirror_file, exc)
            errors.append(f"web mirror failed: {exc}")

    if args.notify:
        notifiable = notifier.should_notify(events, first_run)
        results = notifier.dispatch(
            notifiable, settings.notifier, settings.dashboard_url
        )
        for result in results:
            LOGGER.info("  %-9s %s", result.channel, result.detail)
    else:
        LOGGER.info("--no-notify: skipping dispatch")

    _print_summary(snapshot, settings)
    return EXIT_DEGRADED if errors else EXIT_OK


def command_scrape(args: argparse.Namespace, settings: Settings) -> int:
    """Scrape only — useful for verifying selectors after an ESA redesign."""
    result = scraper.scrape_all(settings)
    for error in result.errors:
        LOGGER.warning(error)
    if not result.opportunities:
        LOGGER.error("no opportunities found")
        return EXIT_FAILURE

    for opportunity in state_manager.sort_for_display(result.opportunities):
        deadline = opportunity.deadline or opportunity.deadline_text or "-"
        print(
            f"[{opportunity.status:7}] {opportunity.title[:64]:64} "
            f"{opportunity.category:26} {deadline}"
        )
    print(f"\n{len(result.opportunities)} opportunities from {len(settings.sources)} sources")
    return EXIT_DEGRADED if result.errors else EXIT_OK


def command_profile(args: argparse.Namespace, settings: Settings) -> int:
    """Print the parsed profile so CV extraction can be eyeballed."""
    profile = profile_parser.build_profile(settings)
    print(f"Name:      {profile.name or '(not detected)'}")
    print(f"Source:    {profile.source_file or '(no PDF found)'}")
    print(f"Headline:  {profile.headline or '-'}")
    print(f"\nEducation ({len(profile.education)}):")
    for item in profile.education:
        print(f"  - {item[:120]}")
    print(f"\nSkills ({len(profile.skills)}): {', '.join(profile.skills) or '-'}")
    print(f"\nHighlights ({len(profile.highlights)}):")
    for item in profile.highlights:
        print(f"  - {item[:120]}")

    github = profile.github
    print(f"\nGitHub: {github.username or '(not configured)'}")
    if github.error:
        print(f"  ! {github.error}")
    for repo in github.repos:
        language = f" [{repo.language}]" if repo.language else ""
        print(f"  - {repo.name}{language}: {repo.description[:80]}")

    if profile.error:
        print(f"\nWarning: {profile.error}", file=sys.stderr)
        return EXIT_DEGRADED
    return EXIT_OK


def command_sme(args: argparse.Namespace, settings: Settings) -> int:
    """Scan the ESA-star SME directory and optionally rank it with the LLM."""
    sme_settings = settings.sme
    previous = sme_state.load_snapshot(sme_settings.data_file)

    LOGGER.info(
        "scanning ESA-star SME directory for %s", ", ".join(sme_settings.countries)
    )
    with Fetcher(
        timeout=settings.timeout,
        max_retries=settings.max_retries,
        user_agent=settings.user_agent,
        use_scrapling=settings.use_scrapling_fetcher,
    ) as fetcher:
        scan = sme_matcher.scan(fetcher, sme_settings)

    errors = list(scan.errors)
    if not scan.companies:
        # Never overwrite a good cache with nothing: the dashboard would go
        # blank on a transient ESA-star outage.
        LOGGER.error("no SME companies matched — leaving %s untouched", sme_settings.data_file)
        for error in errors:
            LOGGER.error("  %s", error)
        return EXIT_FAILURE

    companies = scan.companies
    if args.evaluate:
        LOGGER.info("building profile from CV and GitHub")
        profile = profile_parser.build_profile(settings)
        if profile.error:
            errors.append(f"profile: {profile.error}")
        if profile.github.error:
            errors.append(f"github: {profile.github.error}")

        companies, evaluation_errors = sme_evaluator.evaluate_all(
            companies,
            profile,
            settings.llm,
            target_term=sme_settings.target_term,
            previous=previous.companies,
            max_evaluations=args.limit or sme_settings.max_evaluations,
        )
        errors.extend(evaluation_errors)
    else:
        LOGGER.info("scan only — pass --evaluate to rank companies with the LLM")

    # Carry prior scores forward so a scan-only run (or an LLM outage) never
    # blanks rankings the dashboard already had.
    companies = sme_evaluator.merge_evaluations(companies, previous.companies)

    snapshot = sme_state.build_snapshot(
        companies=companies,
        countries=sme_settings.countries,
        keywords=sme_settings.keywords,
        target_term=sme_settings.target_term,
        scanned=scan.scanned,
        errors=errors,
        evaluated=any(
            c.evaluation is not None and not c.evaluation.error for c in companies
        ),
    )
    sme_state.save_snapshot(
        sme_settings.data_file, snapshot, sme_settings.strong_fit_threshold
    )
    if sme_settings.mirror_file is not None:
        try:
            sme_state.save_snapshot(
                sme_settings.mirror_file, snapshot, sme_settings.strong_fit_threshold
            )
        except OSError as exc:
            LOGGER.warning("could not mirror SME data: %s", exc)
            errors.append(f"web mirror failed: {exc}")

    _print_sme_summary(snapshot, sme_settings)
    return EXIT_DEGRADED if errors else EXIT_OK


def command_export(args: argparse.Namespace, settings: Settings) -> int:
    """Render the stored snapshots as Markdown next to the JSON they came from.

    Reads only what is already on disk — no scraping, no LLM calls — so it is
    safe to run at any time, including straight after a pipeline run.
    """
    output_dir = args.output_dir or REPO_ROOT
    # Neither flag means "both"; the flags narrow the default rather than
    # replacing it, so `--opportunities-only --sme-only` still writes both.
    want_opportunities = args.opportunities or not args.sme
    want_sme = args.sme or not args.opportunities

    written: list[Path] = []
    missing: list[str] = []

    if want_opportunities:
        snapshot = state_manager.load_snapshot(settings.data_file)
        if snapshot.opportunities:
            written.append(
                exporter.write_opportunities(
                    snapshot, output_dir, settings.high_fit_threshold
                )
            )
        else:
            missing.append(
                f"no opportunities in {settings.data_file} — run `python -m agent.main run`"
            )

    if want_sme:
        sme_snapshot = sme_state.load_snapshot(settings.sme.data_file)
        if sme_snapshot.companies:
            written.append(
                exporter.write_sme_targets(
                    sme_snapshot, output_dir, settings.sme.strong_fit_threshold
                )
            )
        else:
            missing.append(
                f"no companies in {settings.sme.data_file} — run "
                f"`python -m agent.main sme --evaluate`"
            )

    for path in written:
        size = path.stat().st_size
        print(f"  wrote {path} ({size:,} bytes)")
    for warning in missing:
        LOGGER.warning(warning)

    if not written:
        LOGGER.error("nothing to export")
        return EXIT_FAILURE
    return EXIT_DEGRADED if missing else EXIT_OK


def command_notify(args: argparse.Namespace, settings: Settings) -> int:
    """Re-send the last run's notifiable events, or a synthetic test alert."""
    if args.test:
        events = (_sample_event(),)
        LOGGER.info("sending a test notification")
    else:
        snapshot = state_manager.load_snapshot(settings.data_file)
        if not snapshot.opportunities:
            LOGGER.error("no state at %s — run `run` first", settings.data_file)
            return EXIT_FAILURE
        events = notifier.should_notify(snapshot.events, first_run=False)
        if not events:
            LOGGER.info("no notifiable events in the last run")
            return EXIT_OK

    results = notifier.dispatch(events, settings.notifier, settings.dashboard_url)
    failed = [r for r in results if r.detail.startswith("failed")]
    for result in results:
        print(f"  {result.channel:9} {result.detail}")
    return EXIT_FAILURE if failed else EXIT_OK


def _sample_event() -> ChangeEvent:
    """A synthetic event used by `notify --test` to verify channel wiring."""
    from .models import Evaluation

    opportunity = Opportunity(
        id="test-opportunity",
        title="ESA Academy Test Alert — Earth Observation Training Course",
        source="esa_tlp",
        source_label="ESA Academy TLP",
        url="https://www.esa.int/Education/ESA_Academy",
        status="Open",
        kind="Training Course",
        category="Earth Observation & AI",
        deadline_text="31 December 2026",
        deadline="2026-12-31",
        evaluation=Evaluation(
            match_score=88,
            justification=(
                "This is a test notification from ESA Scout. If you are reading "
                "it, your notification channel is configured correctly."
            ),
        ),
    )
    return ChangeEvent(
        kind="status_change",
        opportunity=opportunity,
        previous_status="Pending",
        detail="Test alert",
    )


# --- Output helpers --------------------------------------------------------
def _log_events(events: Sequence[ChangeEvent]) -> None:
    if not events:
        LOGGER.info("no changes since the previous run")
        return
    LOGGER.info("%s change event(s):", len(events))
    for event in events[:20]:
        LOGGER.info("  %-16s %s", event.kind, event.opportunity.title[:70])


def _print_summary(snapshot: Snapshot, settings: Settings) -> None:
    stats = snapshot.stats(settings.high_fit_threshold)
    print(
        f"\nESA Scout — {stats['total']} opportunities "
        f"({stats['open']} open, {stats['pending']} pending, {stats['closed']} closed)"
    )
    print(
        f"High fit (>= {settings.high_fit_threshold}%): {stats['high_fit']} · "
        f"AI-evaluated: {stats['evaluated']}"
    )
    top = sorted(snapshot.opportunities, key=lambda o: -o.match_score)[:5]
    if any(o.match_score for o in top):
        print("\nTop matches:")
        for opportunity in top:
            if not opportunity.match_score:
                continue
            print(
                f"  {opportunity.match_score:3d}%  [{opportunity.status:7}] "
                f"{opportunity.title[:64]}"
            )
    if snapshot.errors:
        print(f"\n{len(snapshot.errors)} warning(s):")
        for error in snapshot.errors:
            print(f"  ! {error}")


def _print_sme_summary(snapshot: SmeSnapshot, settings: SmeSettings) -> None:
    stats = snapshot.stats(settings.strong_fit_threshold)
    print(
        f"\nSME Internship Targets — {stats['matched']} matched of "
        f"{stats['scanned']} scanned ({stats['spain']} ES, {stats['italy']} IT)"
    )
    print(
        f"AI-ranked: {stats['evaluated']} · "
        f"Strong fit (>= {settings.strong_fit_threshold}%): {stats['strong_fit']}"
    )
    top = [c for c in snapshot.companies if c.fit_score][:8]
    if top:
        print("\nTop targets:")
        for company in top:
            location = f"{company.city}, {company.country}".strip(", ")
            print(
                f"  {company.fit_score:3d}%  [{company.country_code or '--'}] "
                f"{company.name[:48]:48} {location[:28]}"
            )
    elif not snapshot.evaluated:
        print("\nNot yet ranked — re-run with --evaluate once LLM_API_KEY is set.")
    if snapshot.errors:
        print(f"\n{len(snapshot.errors)} warning(s):")
        for error in snapshot.errors:
            print(f"  ! {error}")


# --- Entry point -----------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esa-scout", description="Scout ESA Academy and careers opportunities."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument(
        "--data-file", type=Path, default=None, help="override data/opportunities.json"
    )
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="full pipeline (default)")
    run.add_argument(
        "--no-notify",
        dest="notify",
        action="store_false",
        default=True,
        help="run everything but do not send notifications",
    )
    run.set_defaults(handler=command_run)

    scrape = subparsers.add_parser("scrape", help="scrape sources and print results")
    scrape.set_defaults(handler=command_scrape)

    profile = subparsers.add_parser("profile", help="show the parsed CV and GitHub data")
    profile.set_defaults(handler=command_profile)

    sme = subparsers.add_parser(
        "sme", help="scan the ESA-star SME directory for internship targets"
    )
    sme.add_argument(
        "--evaluate",
        action="store_true",
        help="rank the matched companies with the LLM (costs API calls)",
    )
    sme.add_argument(
        "--limit",
        type=int,
        default=0,
        help="cap LLM evaluations for this run (overrides SME_MAX_EVALUATIONS)",
    )
    sme.set_defaults(handler=command_sme)

    export = subparsers.add_parser(
        "export", help="write OPPORTUNITIES.md and SME_TARGETS.md from stored data"
    )
    export.add_argument(
        "--opportunities-only",
        dest="opportunities",
        action="store_true",
        help="write only OPPORTUNITIES.md",
    )
    export.add_argument(
        "--sme-only",
        dest="sme",
        action="store_true",
        help="write only SME_TARGETS.md",
    )
    export.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory to write into (default: the repository root)",
    )
    export.set_defaults(handler=command_export)

    notify = subparsers.add_parser("notify", help="dispatch notifications")
    notify.add_argument("--test", action="store_true", help="send a synthetic test alert")
    notify.set_defaults(handler=command_notify)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    if not getattr(args, "command", None):
        # Bare invocation runs the pipeline — this is what the cron calls.
        args = parser.parse_args(["run", *(argv or [])])

    settings = Settings.load(data_file=args.data_file)
    started = dates.utc_now_iso()
    LOGGER.info("ESA Scout starting at %s", started)

    try:
        return args.handler(args, settings)
    except KeyboardInterrupt:
        LOGGER.warning("interrupted")
        return EXIT_FAILURE
    except Exception:
        LOGGER.exception("pipeline failed")
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
