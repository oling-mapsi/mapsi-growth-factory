from app.entrypoints.api import dependencies


def test_get_simple_campaign_service_forces_real_editorial_generation(session, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_build_editorial_generation_service(db_session, *, force_mode=None):
        captured["session"] = db_session
        captured["force_mode"] = force_mode
        return object()

    monkeypatch.setattr(dependencies, "build_editorial_generation_service", fake_build_editorial_generation_service)

    service = dependencies.get_simple_campaign_service(session)

    assert service.require_real_editorial_backend is True
    assert captured["session"] is session
    assert captured["force_mode"] == "real"
