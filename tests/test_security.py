import pytest

from hostinger_file_bridge.security import (
    PathViolation,
    issue_upload_ticket,
    join_remote,
    safe_relative_path,
    verify_upload_ticket,
)


@pytest.mark.parametrize(
    "bad",
    ["/etc/passwd", "../secret", "../../x", "~/.ssh/id_rsa", "", ".", "..", "a/../../b"],
)
def test_reject_bad_paths(bad):
    with pytest.raises(PathViolation):
        safe_relative_path(bad)


def test_join_stays_under_root():
    root = "/home/user/public_html/drop"
    assert join_remote(root, "x/y.zip") == "/home/user/public_html/drop/x/y.zip"


def test_ticket_roundtrip():
    token = issue_upload_ticket(
        secret="a" * 64,
        relative_path="releases/test.zip",
        ttl_seconds=60,
        expected_size=123,
        expected_sha256="b" * 64,
    )
    ticket = verify_upload_ticket(token, "a" * 64)
    assert ticket.relative_path == "releases/test.zip"
    assert ticket.expected_size == 123
    assert ticket.expected_sha256 == "b" * 64


def test_ticket_tamper_rejected():
    token = issue_upload_ticket(
        secret="a" * 64,
        relative_path="test.zip",
        ttl_seconds=60,
    )
    body, sig = token.split(".", 1)
    token = body + "." + ("x" + sig[1:])
    with pytest.raises(ValueError):
        verify_upload_ticket(token, "a" * 64)
