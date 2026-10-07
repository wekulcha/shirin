import pytest
from app.config import Settings
from app.database import database_engine
from pydantic import ValidationError
from sqlalchemy import text


async def test_sqlite_memory_engine_does_not_receive_postgresql_pool_options():
    settings = Settings(_env_file=None, environment="test", database_url="sqlite+aiosqlite:///:memory:")
    engine = database_engine(settings)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
    finally:
        await engine.dispose()


async def test_postgresql_pool_is_bounded_without_connecting():
    settings = Settings(_env_file=None, environment="test", database_url="postgresql+asyncpg://example:example@localhost/example")
    engine = database_engine(settings)
    try:
        assert engine.pool.size() == 2
        assert engine.pool._max_overflow == 1
        assert engine.pool.timeout() == 30
    finally:
        await engine.dispose()


@pytest.mark.parametrize("field,value", [("database_pool_size", 0), ("database_max_overflow", -1), ("database_pool_timeout", 0)])
def test_invalid_pool_budgets_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="test", **{field: value})
