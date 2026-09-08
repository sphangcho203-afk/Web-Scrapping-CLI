import pytest

from internet_hands.policy import PolicyError, validate_public_http_url


def test_blocks_non_http_scheme():
    with pytest.raises(PolicyError):
        validate_public_http_url("file:///etc/passwd")


def test_blocks_embedded_credentials():
    with pytest.raises(PolicyError):
        validate_public_http_url("https://user:pass@example.com/")


def test_blocks_localhost():
    with pytest.raises(PolicyError):
        validate_public_http_url("http://localhost:8080/")
