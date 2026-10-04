"""Database connection helper (psycopg 3, raw SQL, no ORM)."""
import psycopg

from app import config


def get_connection() -> psycopg.Connection:
    """Open a new connection to the giu-bots database.

    Use it as `with get_connection() as conn:` so the transaction is
    committed on success, rolled back on error, and the connection closed.
    """
    return psycopg.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )
