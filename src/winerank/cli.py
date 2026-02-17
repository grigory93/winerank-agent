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

console = Console()


@db_app.command("init")
def db_init():
    """Initialize database by running Alembic migrations."""
    from alembic.config import Config
    from alembic import command
    
    console.print("[bold blue]Initializing database...[/bold blue]")
    
    # Get alembic.ini path
    alembic_ini = Path("alembic.ini")
    if not alembic_ini.exists():
        console.print("[bold red]Error: alembic.ini not found[/bold red]")
        console.print("Make sure you're running from the project root directory")
        raise typer.Exit(1)
    
    try:
        # Run migrations
        alembic_cfg = Config(str(alembic_ini))
        command.upgrade(alembic_cfg, "head")
        console.print("[bold green]✓ Database initialized successfully[/bold green]")
        
        # Seed initial data
        _seed_initial_data()
        
    except Exception as e:
        console.print(f"[bold red]Error initializing database: {e}[/bold red]")
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
    
    from winerank.common.db import reset_db
    
    console.print("[bold blue]Resetting database...[/bold blue]")
    
    try:
        reset_db()
        console.print("[bold green]✓ Database reset successfully[/bold green]")
        
        # Seed initial data
        _seed_initial_data()
        
    except Exception as e:
        console.print(f"[bold red]Error resetting database: {e}[/bold red]")
        raise typer.Exit(1)


def _seed_initial_data():
    """Seed initial data (SiteOfRecord for Michelin)."""
    from winerank.common.db import get_session
    from winerank.common.models import SiteOfRecord
    
    console.print("[bold blue]Seeding initial data...[/bold blue]")
    
    with get_session() as session:
        # Check if Michelin site already exists
        existing = session.query(SiteOfRecord).filter_by(site_name="Michelin Guide USA").first()
        if existing:
            console.print("  • Michelin Guide USA already exists")
            return
        
        # Create Michelin Guide site of record
        michelin = SiteOfRecord(
            site_name="Michelin Guide USA",
            site_url="https://guide.michelin.com/us/en/selection/united-states/restaurants",
            navigational_notes=(
                "Base URL for US restaurants. Use distinction filters:\n"
                "- 3-stars: /3-stars-michelin\n"
                "- 2-stars: /2-stars-michelin\n"
                "- 1-star: /1-star-michelin\n"
                "- Bib Gourmand: /bib-gourmand\n"
                "- Selected: /the-plate-michelin\n"
                "Pagination: /page/N"
            ),
        )
        session.add(michelin)
        session.commit()
        console.print("[bold green]  ✓ Created Michelin Guide USA site of record[/bold green]")


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

        winerank crawl --michelin 3              # all 3-star restaurants

        winerank crawl --restaurant "Per Se"     # single restaurant by name

        winerank crawl --restaurant 5 --force    # single restaurant by ID, force re-crawl
    """
    import logging

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
        elif restaurant:
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
            run_crawler(force_recrawl=force, restaurant_filter=restaurant)
        else:
            settings = get_settings()
            michelin_level = michelin or settings.michelin_level
            mode = " (force re-crawl)" if force else ""
            console.print(
                f"[bold blue]Starting crawler for Michelin {michelin_level} "
                f"restaurants{mode}...[/bold blue]"
            )
            run_crawler(michelin_level=michelin_level, force_recrawl=force)

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
    restaurant: str = typer.Argument(..., help="Restaurant ID or name"),
    file: Optional[Path] = typer.Option(
        None,
        "--file",
        "-f",
        path_type=Path,
        help="Path to wine list PDF (or HTML). If omitted, uses data/downloads/<slug>/ (wine_list.pdf or first .pdf)",
    ),
):
    """Register a manually downloaded wine list and run text extraction.

    Use this when you downloaded the wine list file yourself (e.g. from a
    browser) into the restaurant's download directory. Creates the WineList
    record, extracts text to .txt, and marks the restaurant as WINE_LIST_FOUND.

    Example:

        winerank register-wine-list Smyth

    (Expects a PDF in data/downloads/smyth/ e.g. wine_list.pdf)
    """
    from winerank.common.db import get_session, resolve_restaurant_by_id_or_name
    from winerank.common.models import CrawlStatus, Restaurant, WineList
    from winerank.config import get_settings
    from winerank.crawler.downloader import WineListDownloader
    from winerank.crawler.text_extractor import WineListTextExtractor

    rec = resolve_restaurant_by_id_or_name(restaurant)
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


if __name__ == "__main__":
    app()
