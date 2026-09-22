from internet_hands.control_store import SCHEMA_SQL


def test_connection_schema_separates_public_and_secret_config() -> None:
    assert "CREATE TABLE IF NOT EXISTS ih_connections" in SCHEMA_SQL
    assert "secret_config jsonb" in SCHEMA_SQL
    assert "auth_type text" in SCHEMA_SQL
    assert "transport text" in SCHEMA_SQL
