"""Tests for the health check route (issue #61: raw-string SQL to execute())."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import ArgumentError
from sqlalchemy.sql.elements import TextClause

from api.routes.health import health_check


@pytest.mark.unit
class TestHealthCheckPostgresProbe:
    """Test suite for health_check's Postgres probe."""

    @pytest.fixture
    def mock_db_session(self):
        """A session whose execute() enforces the real SQLAlchemy 2.x rule
        this bug is about: a bare string raises ArgumentError (exactly as
        the live database does), while a text()-wrapped statement succeeds.
        """
        session = AsyncMock()

        async def execute(statement, *args, **kwargs):
            if isinstance(statement, str):
                raise ArgumentError(
                    f"Textual SQL expression {statement!r} should be "
                    f"explicitly declared as text({statement!r})"
                )
            result = MagicMock()
            result.scalar.return_value = 1
            return result

        session.execute = AsyncMock(side_effect=execute)
        return session

    @pytest.mark.asyncio
    async def test_postgres_probe_reports_healthy(self, mock_db_session):
        """The probe must pass a text()-wrapped statement, not a bare
        string, so the Postgres dependency reports healthy.

        The route raises HTTPException(503) whenever any dependency is
        unhealthy; Redis is unhealthy in any environment until #62 is
        fixed (settings has no redis_host), which is out of scope for
        this issue. So this test reads the postgres key off the 503's
        own detail body rather than asserting a 200 overall -- the
        same thing #61 asks about is still directly observable."""
        try:
            result = await health_check(db=mock_db_session)
        except HTTPException as exc:
            result = exc.detail

        assert result["dependencies"]["postgres"] == "healthy"

    @pytest.mark.asyncio
    async def test_postgres_probe_statement_is_textclause(self, mock_db_session):
        """Regression guard for #61: the exact object passed to
        db.execute() must be a TextClause, not a bare str."""
        try:
            await health_check(db=mock_db_session)
        except HTTPException:
            pass  # unrelated to this assertion; see test above

        called_statement = mock_db_session.execute.call_args[0][0]
        assert isinstance(called_statement, TextClause)
        assert not isinstance(called_statement, str)
