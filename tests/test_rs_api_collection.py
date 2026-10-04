import json
from uuid import UUID

import httpx
import pytest

from jgkg.collection_runs import CollectionRun
from jgkg.connectors.rs_api import collect

UID = str(UUID(int=1))


def api_handler(calls, *, invalid=False):
    def handle(request):
        if request.url.path.endswith(f"{UID}/"):
            calls.append(UID)
            if invalid:
                return httpx.Response(200, text="<html>SPA</html>")
            return httpx.Response(200, json={"id": UID, "fiscal_year": 2026,
                                             "is_published": True})
        return httpx.Response(200, json={"count": 1, "next": None, "results": [
            {"id": UID, "fiscal_year": 2026, "is_published": True, "updated_at": "v1"}
        ]})
    return handle


def test_resume_checks_hash_and_refetches_corrupt_raw(tmp_path):
    calls = []
    with httpx.Client(transport=httpx.MockTransport(api_handler(calls))) as client:
        state = collect(2026, tmp_path, "resume", client=client, interval=0)
        assert state["status"] == "complete"
        collect(2026, tmp_path, "resume", client=client, interval=0)
        assert len(calls) == 1
        name = state["snapshots"][f"detail-{UID}"]["filename"]
        (tmp_path / "rs-project-details" / "resume" / name).write_bytes(b"broken")
        collect(2026, tmp_path, "resume", client=client, interval=0)
        assert len(calls) == 2


def test_html_failure_is_recorded_and_can_resume(tmp_path):
    with (httpx.Client(transport=httpx.MockTransport(api_handler([], invalid=True))) as client,
          pytest.raises(ValueError, match="JSON")):
        collect(2026, tmp_path, "retry", client=client, interval=0)
    state = json.loads((tmp_path / "rs-project-details/retry/run.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert f"detail-{UID}" not in state["snapshots"]
    with httpx.Client(transport=httpx.MockTransport(api_handler([]))) as client:
        assert collect(2026, tmp_path, "retry", client=client, interval=0)["status"] == "complete"


def test_changed_inventory_never_marks_complete(tmp_path):
    pages = []
    def handle(request):
        if request.url.path.endswith(f"{UID}/"):
            return httpx.Response(200, json={"id": UID, "fiscal_year": 2026,
                                             "is_published": True})
        pages.append(1)
        return httpx.Response(200, json={"count": 1, "next": None, "results": [
            {"id": UID, "fiscal_year": 2026, "is_published": True,
             "updated_at": str(len(pages))}
        ]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert collect(2026, tmp_path, "changed", client=client, interval=0)["status"] == "partial"


def test_scope_and_lock_prevent_concurrent_or_wrong_year_resume(tmp_path):
    run = CollectionRun(tmp_path, "rs-project-details", "locked", {"fiscal_year": 2026})
    with run.locked(), pytest.raises(FileExistsError), run.locked():
        pass
    wrong = CollectionRun(tmp_path, "rs-project-details", "locked", {"fiscal_year": 2025})
    with pytest.raises(ValueError, match="対象範囲"), wrong.locked():
        pass
