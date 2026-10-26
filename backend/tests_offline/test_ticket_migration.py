import importlib.util
import io
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlmodel import SQLModel, create_engine

REVISION = "a7b8c9d0e1f2"
PARENT = "fe56fa70289e"
MIGRATION = (
    Path(__file__).parents[1]
    / "app"
    / "alembic"
    / "versions"
    / f"{REVISION}_add_ticket.py"
)


def test_ticket_migration_preserves_existing_data_and_enforces_constraints() -> None:
    assert MIGRATION.is_file(), "Ticket migration is missing"
    spec = importlib.util.spec_from_file_location("ticket_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        # Simulate the pre-ticket schema without executing historical PostgreSQL migrations.
        existing_tables = [
            table
            for name, table in SQLModel.metadata.tables.items()
            if name != "ticket"
        ]
        SQLModel.metadata.create_all(connection, tables=existing_tables)
        user_id = "00000000000000000000000000000001"
        connection.execute(
            sa.text(
                'INSERT INTO "user" (id, email, is_active, is_superuser, hashed_password) VALUES (:id, :email, true, false, :password)'
            ),
            {"id": user_id, "email": "preserved@example.com", "password": "test-hash"},
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        assert set(sa.inspect(connection).get_table_names()) == {
            "user",
            "item",
            "ticket",
        }
        assert any(
            index["column_names"] == ["owner_id"]
            for index in sa.inspect(connection).get_indexes("ticket")
        )
        ticket_table = SQLModel.metadata.tables["ticket"]
        row = {
            "id": "00000000000000000000000000000002",
            "title": "Migrated",
            "description": "Details",
            "status": "open",
            "priority": "medium",
            "created_at": "2026-10-25 00:00:00",
            "owner_id": user_id,
        }
        insert = sa.text(
            "INSERT INTO ticket (id, title, description, status, priority, created_at, owner_id) VALUES (:id, :title, :description, :status, :priority, :created_at, :owner_id)"
        )
        connection.execute(insert, row)
        for overrides in [
            {"status": "invalid"},
            {"priority": "invalid"},
            {"title": None},
            {"owner_id": "00000000000000000000000000000099"},
        ]:
            with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
                connection.execute(
                    insert, row | {"id": "00000000000000000000000000000003"} | overrides
                )
        # Compare the migration's shape with the model, not just its existence.
        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns("ticket")
        }
        assert set(columns) == set(ticket_table.columns.keys())
        assert all(not column["nullable"] for column in columns.values())
        with Operations.context(context):
            migration.downgrade()
        assert set(sa.inspect(connection).get_table_names()) == {"user", "item"}
        assert (
            connection.execute(sa.text('SELECT email FROM "user"')).scalar_one()
            == "preserved@example.com"
        )
    engine.dispose()


def test_postgres_migration_sql_and_revision_chain() -> None:
    output = io.StringIO()
    config = Config("alembic.ini", output_buffer=output)
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == REVISION
    command.upgrade(config, f"{PARENT}:{REVISION}", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE ticket" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "ON DELETE CASCADE" in sql
    assert "DROP TABLE" not in sql
    assert "ALTER TABLE" not in sql
    output.seek(0)
    output.truncate(0)
    command.downgrade(config, f"{REVISION}:{PARENT}", sql=True)
    assert "DROP TABLE ticket" in output.getvalue()
