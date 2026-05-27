import typer
from sqlalchemy import create_engine

from fdp.config import database_url_from_env, eodhd_api_key_from_env
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingestion import load_exchange_symbols
from fdp.storage.schema import ensure_runtime_schemas

app = typer.Typer(help="Financial data platform command line interface.")
ingest_app = typer.Typer(help="Ingest source data into the database.")
app.add_typer(ingest_app, name="ingest")


@app.callback()
def main() -> None:
    """Project CLI entrypoint."""


@ingest_app.command("instruments")
def ingest_instruments(
    market: str = typer.Option("US", "--market", help="Market code to ingest."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
) -> None:
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    api_key = eodhd_api_key_from_env()
    engine = create_engine(database_url_from_env())
    client = EodhdClient(api_key=api_key)

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = load_exchange_symbols(connection, client, market=market)

    typer.echo(
        "instrument ingest "
        f"run_id={result.run_id} status={result.status} "
        f"fetched={result.rows_fetched} accepted={result.rows_accepted} "
        f"rejected={result.rows_rejected}"
    )
