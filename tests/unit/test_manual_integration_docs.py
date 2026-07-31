"""Manual Resolve integration matrix policy tests."""

from pathlib import Path


def _matrix_text() -> str:
    return (
        Path(__file__).parents[2]
        / "docs"
        / "manual-integration-testing.md"
    ).read_text(encoding="utf-8")


def test_manual_matrix_covers_required_platform_dimensions() -> None:
    matrix = _matrix_text()

    for required_value in (
        "Windows 10",
        "Windows 11",
        "| 10 | 3.10 | Free",
        "| 10 | 3.11 | Free",
        "| 11 | 3.12 | Free",
        "Free",
        "Studio",
        "Project state",
        "Timeline state",
        "open",
        "absent",
        "none",
        "present",
    ):
        assert required_value in matrix


def test_manual_matrix_distinguishes_verified_and_pending_evidence() -> None:
    matrix = _matrix_text()

    assert "| 10 build 19045 | 3.12.10 | Free | 21.0.3.7 | `verified` |" in (
        matrix
    )
    assert "| 11 | 3.12 | Free | 21.x | `pending` |" in matrix
    assert "| 10 | 3.10–3.12 | Studio | 21.x | `pending` |" in matrix
    assert "GitHub Actions coverage" in matrix
    assert "а не live Resolve" in matrix
    assert "Stale cached heartbeat не зараховується" in matrix


def test_manual_matrix_has_sanitized_evidence_contract() -> None:
    matrix = _matrix_text()

    for required_field in (
        "UTC timestamp",
        "Windows caption, version і build",
        "точну версію Python",
        "agent, bridge і protocol versions",
        "початковий project/timeline state",
        "backup, safety flags та replay result",
    ):
        assert required_field in matrix
    assert "credentials" in matrix
    assert "приватні" in matrix
    assert "media paths" in matrix
    assert r"C:\Users" not in matrix
    assert "G:\\" not in matrix
