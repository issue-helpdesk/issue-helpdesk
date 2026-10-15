import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL")


def test_can_connect_to_database():
    assert DATABASE_URL, "DATABASE_URL is missing"

    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("SELECT 1")