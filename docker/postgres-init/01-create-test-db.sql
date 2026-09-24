-- Runs once, when the Postgres volume is first created.
-- Gives `uv run pytest` its own database, separate from the app's `linkvault` data.
CREATE DATABASE linkvault_test OWNER linkvault;
