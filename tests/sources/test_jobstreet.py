import pytest

from roleradar.sources.jobstreet import JOBSTREET_SEARCH_URL, JobstreetClient


class FakeResponse:
    def __init__(
        self,
        payload: dict | None = None,
        *,
        status_code: int = 200,
        text: str = "",
        headers: dict | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None

    def json(self) -> dict:
        assert self.payload is not None
        return self.payload


class FakeSession:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls: list[dict] = []

    def get(
        self,
        url: str,
        *,
        params: dict,
        headers: dict,
        timeout: float,
    ) -> FakeResponse:
        self.calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        return FakeResponse(self.payloads[params["page"] - 1])


def test_jobstreet_client_uses_chalice_search_parameters_and_paginates() -> None:
    session = FakeSession(
        [
            {"data": [{"id": "job-1"}]},
            {"data": []},
        ]
    )
    client = JobstreetClient(
        session=session,
        timeout_seconds=7.5,
        site_key="SG-Main",
    )

    postings = client.search_jobs(
        query="data analyst",
        location="Singapore",
        max_pages=2,
    )

    assert postings == [{"id": "job-1"}]
    assert session.calls == [
        {
            "url": JOBSTREET_SEARCH_URL,
            "params": {
                "siteKey": "SG-Main",
                "keywords": "data analyst",
                "where": "Singapore",
                "page": 1,
                "seekSelectAllPages": "true",
            },
            "headers": {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.jobstreet.com.sg/",
                "Origin": "https://www.jobstreet.com.sg",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            "timeout": 7.5,
        },
        {
            "url": JOBSTREET_SEARCH_URL,
            "params": {
                "siteKey": "SG-Main",
                "keywords": "data analyst",
                "where": "Singapore",
                "page": 2,
                "seekSelectAllPages": "true",
            },
            "headers": {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.jobstreet.com.sg/",
                "Origin": "https://www.jobstreet.com.sg",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            "timeout": 7.5,
        },
    ]


def test_jobstreet_client_rejects_invalid_max_pages() -> None:
    client = JobstreetClient(session=FakeSession([]))

    with pytest.raises(ValueError, match="max_pages must be at least 1"):
        client.search_jobs(query="data analyst", location="Singapore", max_pages=0)


def test_jobstreet_client_reports_cloudflare_challenge() -> None:
    class BlockedSession:
        def get(
            self,
            url: str,
            *,
            params: dict,
            headers: dict,
            timeout: float,
        ) -> FakeResponse:
            return FakeResponse(
                status_code=403,
                text="<title>Just a moment...</title>",
                headers={"content-type": "text/html; charset=UTF-8"},
            )

    client = JobstreetClient(session=BlockedSession())

    with pytest.raises(RuntimeError, match="Cloudflare challenge"):
        client.search_jobs(query="data analyst", location="Singapore")
