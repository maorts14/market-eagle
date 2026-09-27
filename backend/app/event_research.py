"""External event source boundary. Articles are context, never asserted causes."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import httpx


GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


class EventResearchRateLimited(Exception):
    pass


def fetch_event_articles(query: str, max_records: int = 6) -> list[dict]:
    response = httpx.get(GDELT_DOC_URL, params={
        "query": query, "mode": "artlist", "format": "json", "maxrecords": max_records, "timespan": "1week",
    }, timeout=20)
    if response.status_code == 429:
        raise EventResearchRateLimited("The event provider rate limited this research turn.")
    response.raise_for_status()
    payload = response.json()
    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return [{
        "event_id": sha256(article["url"].encode()).hexdigest(),
        "title": article["title"],
        "url": article["url"],
        "domain": article["domain"],
        "seen_at": datetime.strptime(article["seendate"], "%Y%m%dT%H%M%SZ"),
        "query": query,
        "source_payload": json.dumps(article),
        "fetched_at": fetched_at,
    } for article in payload.get("articles", [])]
