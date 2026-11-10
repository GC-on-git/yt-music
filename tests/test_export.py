"""Export service smoke tests."""

from src.services.assignment_service import AssignmentService
from src.services.export_service import ExportService
from tests.conftest import seed_track


def test_export_csv_and_json(repo) -> None:
    tid = seed_track(repo)
    assignments = AssignmentService(repo)
    dest = assignments.create_destination("Chill")
    assignments.assign(tid, dest)

    exports = ExportService(repo)
    csv_text = exports.to_csv()
    assert "track_id" in csv_text
    assert "Song A" in csv_text

    json_text = exports.to_json()
    assert "Chill" in json_text
    assert "unassigned" in json_text
