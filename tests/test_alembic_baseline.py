import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations

from wlanpi_core.core.models import Base

BASELINE = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "6b98c9fd8477_initial_migration.py"
)


def _load_baseline():
    spec = importlib.util.spec_from_file_location("baseline_migration", BASELINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_upgrade_creates_model_schema_and_downgrade_drops_it():
    baseline = _load_baseline()
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                baseline.upgrade()
            assert sorted(sa.inspect(conn).get_table_names()) == sorted(
                Base.metadata.tables
            )
            assert compare_metadata(ctx, Base.metadata) == []

            with Operations.context(ctx):
                baseline.downgrade()
            assert sa.inspect(conn).get_table_names() == []
    finally:
        engine.dispose()
