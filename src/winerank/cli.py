"""Command-line interface for Winerank using Typer."""
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="winerank",
    help="Winerank - AI agent for wine ranking and recommendations",
    no_args_is_help=True,
)

db_app = typer.Typer(help="Database management commands")
app.add_typer(db_app, name="db")

sft_app = typer.Typer(help="SFT training data generation commands")
app.add_typer(sft_app, name="sft")

console = Console()


def _get_alembic_cfg():
    """Load Alembic config; exit if alembic.ini not found."""
    alembic_ini = Path("alembic.ini")
    if not alembic_ini.exists():
        console.print("[bold red]Error: alembic.ini not found[/bold red]")
        console.print("Make sure you're running from the project root directory")
        raise typer.Exit(1)
    from alembic.config import Config
    return Config(str(alembic_ini))


@db_app.command("init")
def db_init():
    """Initialize database by running Alembic migrations."""
    from alembic import command

    console.print("[bold blue]Initializing database...[/bold blue]")

    try:
        alembic_cfg = _get_alembic_cfg()
        command.upgrade(alembic_cfg, "head")
        command.stamp(alembic_cfg, "head")
        console.print("[bold green]✓ Database initialized successfully[/bold green]")

        _seed_initial_data()

    except Exception as e:
        console.print(f"[bold red]Error initializing database: {e}[/bold red]")
        raise typer.Exit(1)


@db_app.command("stamp")
def db_stamp():
    """Set alembic_version to head without running migrations. Use if init shows revision errors."""
    from alembic import command

    try:
        alembic_cfg = _get_alembic_cfg()
        command.stamp(alembic_cfg, "head")
        console.print("[bold green]✓ Database stamped at head (1cff6e8d6528)[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error stamping database: {e}[/bold red]")
        raise typer.Exit(1)


@db_app.command("reset")
def db_reset(
    confirm: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    )
):
    """Drop and recreate all database tables (destructive!)."""
    if not confirm:
        console.print("[bold yellow]⚠️  WARNING: This will delete ALL data in the database![/bold yellow]")
        proceed = typer.confirm("Are you sure you want to continue?")
        if not proceed:
            console.print("Aborted.")
            raise typer.Exit(0)
    
    from alembic import command
    from winerank.common.db import reset_db

    console.print("[bold blue]Resetting database...[/bold blue]")

    try:
        reset_db()
        alembic_cfg = _get_alembic_cfg()
        command.stamp(alembic_cfg, "head")
        console.print("[bold green]✓ Database reset successfully[/bold green]")

        _seed_initial_data()

    except Exception as e:
        console.print(f"[bold red]Error resetting database: {e}[/bold red]")
        raise typer.Exit(1)


SITES_OF_RECORD = [
    ("Michelin Guide USA", "https://guide.michelin.com/us/en/selection/united-states/restaurants"),
    ("Michelin Guide Canada", "https://guide.michelin.com/us/en/selection/canada/restaurants"),
    ("Michelin Guide Mexico", "https://guide.michelin.com/us/en/selection/mexico/restaurants"),
    ("Michelin Guide Denmark", "https://guide.michelin.com/us/en/selection/denmark/restaurants"),
    ("Michelin Guide France", "https://guide.michelin.com/us/en/selection/france/restaurants"),
    ("Michelin Guide Spain", "https://guide.michelin.com/us/en/selection/spain/restaurants"),
]

NAV_NOTES = (
    "Base URL for restaurants. Use distinction filters:\n"
    "- 3-stars: /3-stars-michelin\n"
    "- 2-stars: /2-stars-michelin\n"
    "- 1-star: /1-star-michelin\n"
    "- Bib Gourmand: /bib-gourmand\n"
    "- Selected: /the-plate-michelin\n"
    "Pagination: /page/N"
)


def _seed_initial_data():
    """Seed initial data (SiteOfRecord for Michelin guides)."""
    from winerank.common.db import get_session
    from winerank.common.models import SiteOfRecord

    console.print("[bold blue]Seeding initial data...[/bold blue]")

    with get_session() as session:
        for site_name, site_url in SITES_OF_RECORD:
            existing = session.query(SiteOfRecord).filter_by(site_name=site_name).first()
            if existing:
                console.print(f"  • {site_name} already exists")
                continue
            site = SiteOfRecord(
                site_name=site_name,
                site_url=site_url,
                navigational_notes=NAV_NOTES,
            )
            session.add(site)
            console.print(f"[bold green]  ✓ Created {site_name} site of record[/bold green]")
        session.commit()


@app.command("db-manager")
def db_manager(
    port: int = typer.Option(8501, "--port", "-p", help="Port to run Streamlit on"),
):
    """Launch the Streamlit database manager UI."""
    import subprocess
    
    console.print(f"[bold blue]Starting DB Manager on port {port}...[/bold blue]")
    
    # Get path to the Streamlit app
    app_path = Path(__file__).parent / "db_manager" / "app.py"
    
    if not app_path.exists():
        console.print(f"[bold red]Error: {app_path} not found[/bold red]")
        raise typer.Exit(1)
    
    try:
        subprocess.run(
            ["streamlit", "run", str(app_path), "--server.port", str(port)],
            check=True,
        )
    except KeyboardInterrupt:
        console.print("\n[bold yellow]DB Manager stopped[/bold yellow]")
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Error running DB Manager: {e}[/bold red]")
        raise typer.Exit(1)


@app.command("crawl")
def crawl(
    michelin: Optional[str] = typer.Option(
        None,
        "--michelin",
        "-m",
        help="Michelin level to crawl (3, 2, 1, gourmand, selected, all)",
    ),
    restaurant: Optional[str] = typer.Option(
        None,
        "--restaurant",
        help=(
            "Crawl a single restaurant by ID (number) or name (text). "
            "Name matching is case-insensitive and supports partial matches."
        ),
    ),
    site: str = typer.Option(
        "USA",
        "--site",
        "-s",
        help="Site of record (e.g. 'Michelin Guide USA' or 'USA'). Default: USA.",
    ),
    resume: Optional[int] = typer.Option(
        None,
        "--resume",
        "-r",
        help="Resume job by ID",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Re-crawl all restaurants even if a wine list was already found",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
):
    """Run the restaurant crawler.

    Examples:

        winerank crawl --michelin 3              # USA 3-star (default site)

        winerank crawl --site Spain --michelin 1

        winerank crawl --restaurant "Per Se"     # single restaurant by name

        winerank crawl --restaurant 5 --force    # single restaurant by ID, force re-crawl
    """
    import logging

    from winerank.common.db import get_session, resolve_site_by_name
    from winerank.common.models import SiteOfRecord
    from winerank.config import get_settings
    from winerank.crawler.workflow import run_crawler

    # Configure logging – only our own loggers get DEBUG; third-party stays at WARNING
    log_fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    logging.basicConfig(level=logging.WARNING, format=log_fmt, datefmt="%H:%M:%S")
    winerank_level = logging.DEBUG if verbose else logging.INFO
    logging.getLogger("winerank").setLevel(winerank_level)

    try:
        if resume:
            console.print(f"[bold blue]Resuming crawler job {resume}...[/bold blue]")
            run_crawler(resume_job_id=resume, force_recrawl=force,
                        restaurant_filter=restaurant)
        else:
            with get_session() as session:
                site_rec = resolve_site_by_name(session, site)
                if not site_rec:
                    console.print(
                        f"[bold red]Site not found: {site!r}. "
                        "Available sites:[/bold red]"
                    )
                    for s in session.query(SiteOfRecord).order_by(SiteOfRecord.site_name).all():
                        console.print(f"  • {s.site_name}")
                    raise typer.Exit(1)
                site_of_record_id = site_rec.id
                site_name = site_rec.site_name

            if restaurant:
                if michelin:
                    console.print(
                        "[yellow]--restaurant takes priority; "
                        "ignoring --michelin[/yellow]"
                    )
                mode = " (force re-crawl)" if force else ""
                console.print(
                    f"[bold blue]Crawling single restaurant: "
                    f"{restaurant}{mode}...[/bold blue]"
                )
                run_crawler(
                    site_of_record_id=site_of_record_id,
                    force_recrawl=force,
                    restaurant_filter=restaurant,
                )
            else:
                settings = get_settings()
                michelin_level = michelin or settings.michelin_level
                mode = " (force re-crawl)" if force else ""
                console.print(
                    f"[bold blue]Starting crawler for Michelin {michelin_level} "
                    f"restaurants ({site_name}){mode}...[/bold blue]"
                )
                run_crawler(
                    site_of_record_id=site_of_record_id,
                    michelin_level=michelin_level,
                    force_recrawl=force,
                )

        console.print("[bold green]✓ Crawler completed successfully[/bold green]")

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Crawler interrupted by user[/bold yellow]")
        raise typer.Exit(0)
    except Exception as e:
        console.print(f"[bold red]Error running crawler: {e}[/bold red]")
        raise typer.Exit(1)


@app.command("crawl-status")
def crawl_status():
    """Show status of recent crawler jobs."""
    from winerank.common.db import get_session
    from winerank.common.models import Job
    
    with get_session() as session:
        jobs = session.query(Job).order_by(Job.started_at.desc()).limit(10).all()
        
        if not jobs:
            console.print("[yellow]No jobs found[/yellow]")
            return
        
        table = Table(title="Recent Crawler Jobs")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Level", style="blue")
        table.add_column("Status", style="green")
        table.add_column("Progress", style="yellow")
        table.add_column("Started", style="white")
        
        for job in jobs:
            progress = f"{job.restaurants_processed}/{job.restaurants_found}"
            table.add_row(
                str(job.id),
                job.job_type,
                job.michelin_level or "N/A",
                job.status.value,
                progress,
                job.started_at.strftime("%Y-%m-%d %H:%M"),
            )
        
        console.print(table)


@app.command("register-wine-list")
def register_wine_list(
    restaurant: str = typer.Option(
        ...,
        "--restaurant",
        "-r",
        help="Restaurant ID or name",
    ),
    file: Optional[Path] = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to wine list PDF (or HTML). If omitted, uses data/downloads/<slug>/ (wine_list.pdf or first .pdf)",
    ),
    site: Optional[str] = typer.Option(
        None,
        "--site",
        "-s",
        help="Site of record to disambiguate by name (e.g. USA, France). Ignored when restaurant is an ID.",
    ),
):
    """Register a manually downloaded wine list and run text extraction.

    Use this when you downloaded the wine list file yourself (e.g. from a
    browser) into the restaurant's download directory. Creates the WineList
    record, extracts text to .txt, and marks the restaurant as WINE_LIST_FOUND.

    Examples:

        winerank register-wine-list --restaurant Smyth

        winerank register-wine-list --restaurant "Per Se" --file ~/Downloads/wine_list.pdf

        winerank register-wine-list --restaurant "Le Bernardin" --site USA

    (When --file is omitted, expects a PDF in data/downloads/<slug>/ e.g. wine_list.pdf)
    """
    from winerank.common.db import get_session, resolve_restaurant_by_id_or_name, resolve_site_by_name
    from winerank.common.models import CrawlStatus, Restaurant, WineList
    from winerank.config import get_settings
    from winerank.crawler.downloader import WineListDownloader
    from winerank.crawler.text_extractor import WineListTextExtractor

    site_of_record_id = None
    if site:
        with get_session() as session:
            site_rec = resolve_site_by_name(session, site)
            if not site_rec:
                console.print(
                    f"[bold red]Site not found: {site!r}. "
                    "Use a site name or short name (e.g. USA, France).[/bold red]"
                )
                raise typer.Exit(1)
            site_of_record_id = site_rec.id
    rec = resolve_restaurant_by_id_or_name(restaurant, site_of_record_id=site_of_record_id)
    if not rec:
        console.print(f"[bold red]Restaurant not found: {restaurant}[/bold red]")
        raise typer.Exit(1)

    restaurant_id, name, wine_list_url = rec.id, rec.name, rec.wine_list_url
    settings = get_settings()
    download_path = settings.download_path

    if file is not None:
        path = file.resolve()
        if not path.is_file():
            console.print(f"[bold red]File not found or not a file: {path}[/bold red]")
            raise typer.Exit(1)
    else:
        slug = name.lower().replace(" ", "-").replace("'", "")
        dir_path = download_path / slug
        if not dir_path.is_dir():
            console.print(
                f"[bold red]No download directory for {name}. "
                f"Create {dir_path} and add a PDF, or use --file path[/bold red]"
            )
            raise typer.Exit(1)
        candidate = dir_path / "wine_list.pdf"
        if candidate.exists():
            path = candidate
        else:
            pdfs = sorted(dir_path.glob("*.pdf"))
            if not pdfs:
                console.print(
                    f"[bold red]No PDF found in {dir_path}. "
                    f"Add wine_list.pdf or use --file path[/bold red]"
                )
                raise typer.Exit(1)
            path = pdfs[0]

    console.print(f"[bold blue]Registering wine list for {name} from {path}[/bold blue]")

    raw = path.read_bytes()
    file_hash = WineListDownloader._compute_hash(raw)

    try:
        extractor = WineListTextExtractor()
        text_path = extractor.extract_and_save(str(path))
    except Exception as e:
        console.print(f"[bold red]Error extracting text: {e}[/bold red]")
        raise typer.Exit(1)

    source_url = wine_list_url if wine_list_url else "manual"

    with get_session() as session:
        rec = session.query(Restaurant).filter_by(id=restaurant_id).first()
        if not rec:
            console.print(f"[bold red]Restaurant {restaurant_id} no longer in DB[/bold red]")
            raise typer.Exit(1)

        wine_list = WineList(
            restaurant_id=restaurant_id,
            list_name=f"{name} Wine List",
            source_url=source_url,
            local_file_path=str(path),
            file_hash=file_hash,
            wine_count=0,
        )
        session.add(wine_list)
        wine_list.text_file_path = text_path
        rec.crawl_status = CrawlStatus.WINE_LIST_FOUND
        if wine_list_url:
            rec.wine_list_url = wine_list_url
        session.commit()

    console.print(f"[bold green]Wine list registered (id={wine_list.id}), text saved to {text_path}[/bold green]")


# ---------------------------------------------------------------------------
# SFT subcommands
# ---------------------------------------------------------------------------


def _sft_settings_override(
    taxonomy_model: Optional[str],
    teacher_model: Optional[str],
    judge_model: Optional[str],
    mode: Optional[str],
    seed: Optional[int],
    num_samples: Optional[int],
    min_judge_score: Optional[float],
    batch: Optional[bool] = None,
):
    """Load SFT settings and apply any CLI overrides."""
    from winerank.sft.config import SFTSettings

    kwargs: dict = {}
    if taxonomy_model:
        kwargs["taxonomy_model"] = taxonomy_model
    if teacher_model:
        kwargs["teacher_model"] = teacher_model
    if judge_model:
        kwargs["judge_model"] = judge_model
    if mode:
        kwargs["training_data_mode"] = mode
    if seed is not None:
        kwargs["seed"] = seed
    if num_samples is not None:
        kwargs["num_samples"] = num_samples
    if min_judge_score is not None:
        kwargs["min_judge_score"] = min_judge_score
    if batch is not None:
        kwargs["batch_mode"] = batch
    return SFTSettings(**kwargs)


@sft_app.command("init")
def sft_init(
    examples_dir: Optional[Path] = typer.Option(
        None,
        "--examples-dir",
        help="Directory with wine list files (default: data/examples)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output path for manifest.yaml (default: data/sft/manifest.yaml)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing manifest"),
):
    """Generate manifest.yaml from wine lists in the examples directory."""
    from winerank.sft.config import SFTSettings
    from winerank.sft.manifest import generate_manifest, save_manifest

    settings = SFTSettings()
    examples_path = examples_dir or Path(settings.examples_dir)
    manifest_path = output or settings.manifest_file

    if manifest_path.exists() and not force:
        console.print(f"[yellow]Manifest already exists at {manifest_path}. Use --force to overwrite.[/yellow]")
        raise typer.Exit(0)

    if not examples_path.exists():
        console.print(f"[bold red]Examples directory not found: {examples_path}[/bold red]")
        raise typer.Exit(1)

    manifest = generate_manifest(examples_path)
    save_manifest(manifest, manifest_path)

    console.print(f"[bold green]✓ Manifest created at {manifest_path}[/bold green]")
    console.print(f"  {len(manifest.lists)} wine lists registered")


@sft_app.command("extract-taxonomy")
def sft_extract_taxonomy(
    taxonomy_model: Optional[str] = typer.Option(None, "--taxonomy-model", help="Override taxonomy model"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-run already completed extractions"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without LLM calls"),
    batch: Optional[bool] = typer.Option(None, "--batch/--no-batch", help="Use batch API (50% cheaper, async)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Process only first N wine lists (for testing)"),
):
    """Phase 1: Validate wine lists and extract taxonomy for all entries."""
    from winerank.sft.config import SFTSettings
    from winerank.sft.manifest import load_manifest
    from winerank.sft.progress import ProgressTracker
    from winerank.sft.taxonomy_extractor import extract_taxonomy_for_all

    settings = SFTSettings()
    if taxonomy_model or batch is not None:
        settings = SFTSettings(
            taxonomy_model=taxonomy_model or settings.taxonomy_model,
            batch_mode=batch if batch is not None else settings.batch_mode,
        )

    settings.ensure_dirs()

    try:
        manifest = load_manifest(settings.manifest_file)
    except FileNotFoundError:
        console.print("[bold red]Manifest not found. Run 'winerank sft init' first.[/bold red]")
        raise typer.Exit(1)

    entries = manifest.lists[:limit] if limit else manifest.lists
    progress = ProgressTracker(settings.progress_file)
    if force:
        progress.reset()

    batch_label = " [batch mode]" if settings.batch_mode else ""
    limit_label = f" (limited to {limit})" if limit else ""
    console.print(
        f"[bold blue]Extracting taxonomy for {len(entries)} wine lists{limit_label}{batch_label}...[/bold blue]"
    )
    if dry_run:
        console.print("[yellow]DRY RUN mode - no LLM calls will be made[/yellow]")

    results = extract_taxonomy_for_all(
        entries,
        settings=settings,
        progress=progress,
        force=force,
        dry_run=dry_run,
    )

    ok = sum(1 for r in results.values() if r and r.status == "OK")
    not_list = sum(1 for r in results.values() if r and r.status == "NOT_A_LIST")
    errors = sum(1 for r in results.values() if r is None)

    console.print("[bold green]✓ Taxonomy extraction complete[/bold green]")
    console.print(f"  OK: {ok} | NOT_A_LIST: {not_list} | Errors: {errors}")


@sft_app.command("sample")
def sft_sample(
    seed: Optional[int] = typer.Option(None, "--seed", help="Random seed"),
    num_samples: Optional[int] = typer.Option(None, "--num-samples", "-n", help="Target sample count"),
    force: bool = typer.Option(False, "--force", "-f", help="Regenerate even if samples.json exists"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Only sample from first N wine lists (for testing)"),
):
    """Phase 2: Stratified random sampling of wine list segments."""
    from winerank.sft.config import SFTSettings
    from winerank.sft.manifest import load_manifest
    from winerank.sft.page_sampler import save_samples, sample_segments
    from winerank.sft.progress import ProgressTracker

    settings = SFTSettings()
    if seed is not None or num_samples is not None:
        settings = SFTSettings(
            seed=seed if seed is not None else settings.seed,
            num_samples=num_samples if num_samples is not None else settings.num_samples,
        )

    if settings.samples_file.exists() and not force:
        console.print("[yellow]samples.json already exists. Use --force to regenerate.[/yellow]")
        raise typer.Exit(0)

    try:
        manifest = load_manifest(settings.manifest_file)
    except FileNotFoundError:
        console.print("[bold red]Manifest not found. Run 'winerank sft init' first.[/bold red]")
        raise typer.Exit(1)

    progress = ProgressTracker(settings.progress_file)
    not_a_list_ids = progress.get_not_a_list_ids()

    entries = manifest.lists[:limit] if limit else manifest.lists
    limit_label = f" (limited to first {limit} lists)" if limit else ""
    # When limit is set, scale num_samples so per-list allocation stays the same
    total_lists = len(manifest.lists)
    effective_num_samples = (
        max(1, round(settings.num_samples * len(entries) / total_lists))
        if limit and total_lists > 0
        else settings.num_samples
    )
    console.print(
        f"[bold blue]Sampling {effective_num_samples} segments from {len(entries)} lists"
        f"{limit_label} (seed={settings.seed})...[/bold blue]"
    )

    samples = sample_segments(
        entries=entries,
        not_a_list_ids=not_a_list_ids,
        num_samples=effective_num_samples,
        seed=settings.seed,
        min_per_list=settings.min_segments_per_list,
        min_chars=settings.min_segment_chars,
    )
    settings.ensure_dirs()
    save_samples(samples, settings.samples_file)
    console.print(f"[bold green]✓ {len(samples)} segments sampled → {settings.samples_file}[/bold green]")


@sft_app.command("parse")
def sft_parse(
    teacher_model: Optional[str] = typer.Option(None, "--teacher-model", help="Override teacher model"),
    mode: Optional[str] = typer.Option(None, "--mode", help="Input mode: vision or text"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-run already completed parses"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without LLM calls"),
    batch: Optional[bool] = typer.Option(None, "--batch/--no-batch", help="Use batch API (50% cheaper, async)"),
):
    """Phase 3: Parse wine entries from sampled segments using the Teacher model."""
    from winerank.sft.config import SFTSettings
    from winerank.sft.page_sampler import load_samples
    from winerank.sft.progress import ProgressTracker
    from winerank.sft.wine_parser import parse_all_segments

    settings = SFTSettings()
    if teacher_model or mode or batch is not None:
        settings = SFTSettings(
            teacher_model=teacher_model or settings.teacher_model,
            training_data_mode=mode or settings.training_data_mode,
            batch_mode=batch if batch is not None else settings.batch_mode,
        )

    settings.ensure_dirs()

    try:
        samples = load_samples(settings.samples_file)
    except FileNotFoundError:
        console.print("[bold red]samples.json not found. Run 'winerank sft sample' first.[/bold red]")
        raise typer.Exit(1)

    progress = ProgressTracker(settings.progress_file)

    batch_label = " [batch mode]" if settings.batch_mode else ""
    console.print(
        f"[bold blue]Parsing {len(samples)} segments with {settings.teacher_model} "
        f"(mode={settings.training_data_mode}){batch_label}...[/bold blue]"
    )
    if dry_run:
        console.print("[yellow]DRY RUN mode[/yellow]")

    results = parse_all_segments(samples, settings=settings, progress=progress, force=force, dry_run=dry_run)
    ok = sum(1 for r in results if not r.parse_error)
    errors = sum(1 for r in results if r.parse_error)
    console.print(f"[bold green]✓ Parsing complete: {ok} OK, {errors} errors[/bold green]")


@sft_app.command("judge")
def sft_judge(
    judge_model: Optional[str] = typer.Option(None, "--judge-model", help="Override judge model"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-run already completed reviews"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without LLM calls"),
    batch: Optional[bool] = typer.Option(None, "--batch/--no-batch", help="Use batch API (50% cheaper, async)"),
):
    """Phase 3.5: Run optional Judge model to score parsed segments."""
    from winerank.sft.config import SFTSettings
    from winerank.sft.judge_reviewer import judge_all_segments
    from winerank.sft.progress import ProgressTracker
    from winerank.sft.wine_parser import load_all_parse_results

    settings = SFTSettings()
    if judge_model or batch is not None:
        settings = SFTSettings(
            judge_model=judge_model or settings.judge_model,
            batch_mode=batch if batch is not None else settings.batch_mode,
        )

    settings.ensure_dirs()
    parse_results = load_all_parse_results(settings.parsed_dir)
    if not parse_results:
        console.print("[yellow]No parsed results found. Run 'winerank sft parse' first.[/yellow]")
        raise typer.Exit(0)

    progress = ProgressTracker(settings.progress_file)

    batch_label = " [batch mode]" if settings.batch_mode else ""
    console.print(
        f"[bold blue]Running Judge on {len(parse_results)} segments with {settings.judge_model}{batch_label}...[/bold blue]"
    )
    if dry_run:
        console.print("[yellow]DRY RUN mode[/yellow]")

    results = judge_all_segments(parse_results, settings=settings, progress=progress, force=force, dry_run=dry_run)
    accept = sum(1 for r in results if r.recommendation == "accept")
    review = sum(1 for r in results if r.recommendation == "review")
    reject = sum(1 for r in results if r.recommendation == "reject")
    avg_score = sum(r.score for r in results) / len(results) if results else 0.0

    console.print(
        f"[bold green]✓ Judge complete: accept={accept} review={review} "
        f"reject={reject} avg_score={avg_score:.2f}[/bold green]"
    )


@sft_app.command("build")
def sft_build(
    min_judge_score: Optional[float] = typer.Option(None, "--min-judge-score", help="Minimum judge score to include (0.0-1.0)"),
):
    """Phase 4: Assemble final SFT-ready JSONL training dataset."""
    from winerank.sft.config import get_sft_settings
    from winerank.sft.dataset_builder import build_dataset
    from winerank.sft.progress import ProgressTracker

    from winerank.sft.config import SFTSettings
    settings = SFTSettings()
    settings.ensure_dirs()
    progress = ProgressTracker(settings.progress_file)

    console.print("[bold blue]Building training dataset...[/bold blue]")
    jsonl_path = build_dataset(settings=settings, progress=progress, min_judge_score=min_judge_score)

    from winerank.sft.dataset_builder import load_dataset_metadata
    meta = load_dataset_metadata(settings.dataset_dir)
    if meta:
        console.print(f"[bold green]✓ Dataset built: {meta.num_samples_actual} samples → {jsonl_path}[/bold green]")
        console.print(f"  Lists used: {meta.num_lists_used}")
        console.print(f"  NOT_A_LIST filtered: {meta.not_a_list_count}")
        console.print(f"  Judge filtered: {meta.judge_filtered_count}")


@sft_app.command("run")
def sft_run(
    taxonomy_model: Optional[str] = typer.Option(None, "--taxonomy-model"),
    teacher_model: Optional[str] = typer.Option(None, "--teacher-model"),
    judge_model: Optional[str] = typer.Option(None, "--judge-model"),
    mode: Optional[str] = typer.Option(None, "--mode"),
    seed: Optional[int] = typer.Option(None, "--seed"),
    num_samples: Optional[int] = typer.Option(None, "--num-samples", "-n"),
    min_judge_score: Optional[float] = typer.Option(None, "--min-judge-score"),
    skip_judge: bool = typer.Option(False, "--skip-judge", help="Skip the judge review phase"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-run all phases"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without LLM calls"),
    batch: Optional[bool] = typer.Option(None, "--batch/--no-batch", help="Use batch API (50% cheaper, async)"),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l",
        help="Process only first N wine lists (for testing; applies to taxonomy and sampling)",
    ),
):
    """Run the full SFT pipeline end-to-end (init → taxonomy → sample → parse → [judge] → build)."""
    from winerank.sft.config import SFTSettings
    from winerank.sft.dataset_builder import build_dataset, load_dataset_metadata
    from winerank.sft.executor import create_executor
    from winerank.sft.judge_reviewer import (
        load_all_judge_results,
        prepare_judge_requests,
        process_judge_responses,
    )
    from winerank.sft.manifest import generate_manifest, load_manifest, save_manifest
    from winerank.sft.page_sampler import load_samples, sample_segments, save_samples
    from winerank.sft.progress import ProgressTracker
    from winerank.sft.taxonomy_extractor import (
        load_taxonomy,
        prepare_taxonomy_requests,
        process_taxonomy_responses,
    )
    from winerank.sft.wine_parser import (
        load_all_parse_results,
        prepare_parse_requests,
        process_parse_responses,
    )

    settings_kwargs: dict = {}
    if taxonomy_model:
        settings_kwargs["taxonomy_model"] = taxonomy_model
    if teacher_model:
        settings_kwargs["teacher_model"] = teacher_model
    if judge_model:
        settings_kwargs["judge_model"] = judge_model
    if mode:
        settings_kwargs["training_data_mode"] = mode
    if seed is not None:
        settings_kwargs["seed"] = seed
    if num_samples is not None:
        settings_kwargs["num_samples"] = num_samples
    if min_judge_score is not None:
        settings_kwargs["min_judge_score"] = min_judge_score
    if batch is not None:
        settings_kwargs["batch_mode"] = batch

    settings = SFTSettings(**settings_kwargs)
    settings.ensure_dirs()
    progress = ProgressTracker(settings.progress_file)

    if force:
        progress.reset()

    batch_label = " [BATCH MODE - up to 24h turnaround, 50% cheaper]" if settings.batch_mode else ""
    limit_label = f" (limited to first {limit} lists)" if limit else ""
    console.print(
        f"[bold blue]Running full SFT pipeline{limit_label}{batch_label}...[/bold blue]"
    )

    # Init manifest if not present
    if not settings.manifest_file.exists():
        examples_path = Path(settings.examples_dir)
        if not examples_path.exists():
            console.print(f"[bold red]Examples directory not found: {examples_path}[/bold red]")
            raise typer.Exit(1)
        manifest = generate_manifest(examples_path)
        save_manifest(manifest, settings.manifest_file)
        console.print(f"[green]✓ Manifest generated ({len(manifest.lists)} lists)[/green]")
    else:
        manifest = load_manifest(settings.manifest_file)

    entries = manifest.lists[:limit] if limit else manifest.lists
    entries_by_id = {e.list_id: e for e in entries}

    # Create the executor once -- all three phases reuse the same instance
    executor = create_executor(
        batch_mode=settings.batch_mode,
        data_dir=settings.data_path,
        batch_timeout=settings.batch_timeout,
    )

    # ------------------------------------------------------------------
    # Phase 1: Taxonomy
    # ------------------------------------------------------------------
    console.print(f"[blue]Phase 1: Extracting taxonomy for {len(entries)} lists...[/blue]")
    if dry_run:
        console.print("[yellow]  DRY RUN - no LLM calls[/yellow]")
        taxonomies: dict = {e.list_id: None for e in entries}
    else:
        tax_requests = prepare_taxonomy_requests(entries, settings, progress, force=force)
        if tax_requests:
            tax_responses = executor.execute(tax_requests)
            taxonomies = process_taxonomy_responses(
                tax_responses, settings, progress, entries_by_id=entries_by_id
            )
        else:
            taxonomies = {}
        # Add already-completed taxonomy results
        for entry in entries:
            if entry.list_id not in taxonomies:
                tax = load_taxonomy(settings.taxonomy_dir, entry.list_id)
                if tax:
                    taxonomies[entry.list_id] = tax
        ok = sum(1 for t in taxonomies.values() if t and t.status == "OK")
        not_list = sum(1 for t in taxonomies.values() if t and t.status == "NOT_A_LIST")
        console.print(f"  [green]✓ Taxonomy: {ok} OK, {not_list} NOT_A_LIST[/green]")

    # ------------------------------------------------------------------
    # Phase 2: Sampling (always local, no LLM)
    # ------------------------------------------------------------------
    console.print("[blue]Phase 2: Sampling segments...[/blue]")
    not_a_list_ids = progress.get_not_a_list_ids()
    # When limit is set, scale num_samples so per-list allocation stays the same
    total_lists = len(manifest.lists)
    effective_num_samples = (
        max(1, round(settings.num_samples * len(entries) / total_lists))
        if limit and total_lists > 0
        else settings.num_samples
    )
    samples = sample_segments(
        entries=entries,
        not_a_list_ids=not_a_list_ids,
        num_samples=effective_num_samples,
        seed=settings.seed,
        min_per_list=settings.min_segments_per_list,
        min_chars=settings.min_segment_chars,
    )
    save_samples(samples, settings.samples_file)
    console.print(f"  [green]✓ {len(samples)} segments sampled[/green]")

    # ------------------------------------------------------------------
    # Phase 3: Wine Parsing
    # ------------------------------------------------------------------
    console.print(
        f"[blue]Phase 3: Parsing {len(samples)} segments with {settings.teacher_model}...[/blue]"
    )
    if not dry_run:
        parse_requests = prepare_parse_requests(
            samples, taxonomies, settings, progress, force=force
        )
        samples_by_id = {
            f"parse__{s.list_id}__{s.segment_index}": s for s in samples
        }
        if parse_requests:
            parse_responses = executor.execute(parse_requests)
            process_parse_responses(parse_responses, samples_by_id, settings, progress)
        parse_results = load_all_parse_results(settings.parsed_dir)
        ok_p = sum(1 for r in parse_results if not r.parse_error)
        err_p = sum(1 for r in parse_results if r.parse_error)
        console.print(f"  [green]✓ Parse: {ok_p} OK, {err_p} errors[/green]")
    else:
        parse_results = []
        console.print("[yellow]  DRY RUN - skipping parse[/yellow]")

    # ------------------------------------------------------------------
    # Phase 3.5: Judge (optional)
    # ------------------------------------------------------------------
    if not skip_judge and not dry_run:
        console.print(
            f"[blue]Phase 3.5: Running Judge on {len(parse_results)} segments with {settings.judge_model}...[/blue]"
        )
        judge_requests = prepare_judge_requests(parse_results, settings, progress, force=force)
        if judge_requests:
            judge_responses = executor.execute(judge_requests)
            process_judge_responses(judge_responses, settings, progress)
        judge_results = load_all_judge_results(settings.judged_dir)
        accept = sum(1 for r in judge_results.values() if r.recommendation == "accept")
        review_c = sum(1 for r in judge_results.values() if r.recommendation == "review")
        reject = sum(1 for r in judge_results.values() if r.recommendation == "reject")
        console.print(f"  [green]✓ Judge: accept={accept} review={review_c} reject={reject}[/green]")

    # ------------------------------------------------------------------
    # Phase 4: Build dataset
    # ------------------------------------------------------------------
    console.print("[blue]Phase 4: Building dataset...[/blue]")
    jsonl_path = build_dataset(settings=settings, progress=progress, min_judge_score=min_judge_score)

    meta = load_dataset_metadata(settings.dataset_dir)
    if meta:
        console.print(
            f"[bold green]✓ Pipeline complete: {meta.num_samples_actual} samples → {jsonl_path}[/bold green]"
        )


@sft_app.command("stats")
def sft_stats():
    """Show dataset statistics and pipeline progress summary."""
    from winerank.sft.config import get_sft_settings
    from winerank.sft.dataset_builder import load_dataset_metadata
    from winerank.sft.judge_reviewer import load_all_judge_results
    from winerank.sft.progress import ProgressTracker

    from winerank.sft.config import SFTSettings
    settings = SFTSettings()
    progress = ProgressTracker(settings.progress_file)
    summary = progress.summary()
    tokens = progress.total_tokens()

    table = Table(title="SFT Pipeline Progress")
    table.add_column("Phase", style="cyan")
    table.add_column("OK", style="green")
    table.add_column("Errors / Special", style="red")
    table.add_column("Total", style="white")

    tax = summary["taxonomy"]
    table.add_row("Taxonomy", str(tax["ok"]), f"not_a_list={tax['not_a_list']} err={tax['error']}", str(tax["total"]))

    parse = summary["parse"]
    table.add_row("Parse", str(parse["ok"]), str(parse["error"]), str(parse["total"]))

    judge = summary["judge"]
    table.add_row("Judge", str(judge["ok"]), str(judge["error"]), str(judge["total"]))

    console.print(table)

    # Token stats
    console.print(f"\n[bold]Token Usage:[/bold]")
    console.print(f"  Input tokens:  {tokens['input']:,}")
    console.print(f"  Output tokens: {tokens['output']:,}")
    console.print(f"  Cached tokens: {tokens['cached']:,}")

    # Judge distribution
    judge_results = load_all_judge_results(settings.judged_dir)
    if judge_results:
        accept = sum(1 for r in judge_results.values() if r.recommendation == "accept")
        review = sum(1 for r in judge_results.values() if r.recommendation == "review")
        reject = sum(1 for r in judge_results.values() if r.recommendation == "reject")
        avg_score = sum(r.score for r in judge_results.values()) / len(judge_results)
        console.print(f"\n[bold]Judge Results:[/bold]")
        console.print(f"  Accept: {accept} | Review: {review} | Reject: {reject}")
        console.print(f"  Average score: {avg_score:.3f}")

    # Dataset metadata
    meta = load_dataset_metadata(settings.dataset_dir)
    if meta:
        console.print(f"\n[bold]Dataset:[/bold]")
        console.print(f"  Samples: {meta.num_samples_actual} (target: {meta.num_samples_target})")
        console.print(f"  Lists used: {meta.num_lists_used}")
        console.print(f"  Generated at: {meta.generated_at}")
        console.print(f"  Teacher model: {meta.teacher_model}")
        console.print(f"  Mode: {meta.training_data_mode}")


if __name__ == "__main__":
    app()
