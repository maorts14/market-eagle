from app import event_research


class _Response:
    status_code = 200

    def json(self) -> dict:
        return {"articles": [{
            "url": "https://example.com/article", "title": "Test market event", "domain": "example.com",
            "seendate": "20260927T120000Z",
        }]}

    def raise_for_status(self) -> None:
        return None


def test_event_articles_preserve_auditable_source_fields(monkeypatch) -> None:
    monkeypatch.setattr(event_research.httpx, "get", lambda *args, **kwargs: _Response())
    rows = event_research.fetch_event_articles('"Energy" "Industrials"')
    assert rows[0]["title"] == "Test market event"
    assert rows[0]["url"] == "https://example.com/article"
    assert rows[0]["domain"] == "example.com"


def test_event_articles_surface_rate_limits(monkeypatch) -> None:
    class RateLimitedResponse:
        status_code = 429

    monkeypatch.setattr(event_research.httpx, "get", lambda *args, **kwargs: RateLimitedResponse())
    try:
        event_research.fetch_event_articles('"Energy"')
    except event_research.EventResearchRateLimited:
        return
    assert False, "Expected an explicit rate-limit outcome"
