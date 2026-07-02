import pytest

from roleradar.sources.careers_gov import API_LINK, CareersGovClient


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
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
        return FakeResponse(self.payloads[params["page"]])


def test_careers_gov_client_uses_requested_api_link_and_paginates() -> None:
    session = FakeSession(
        [
            {"results": [{"uuid": "job-1"}]},
            {"results": []},
        ]
    )
    client = CareersGovClient(
        session=session,
        timeout_seconds=7.5,
        throttle_seconds=0,
    )

    postings = client.search_jobs(query="data analyst", limit=1, max_pages=2)

    assert postings == [{"uuid": "job-1"}]
    assert session.calls == [
        {
            "url": API_LINK,
            "params": {"limit": 1, "page": 0, "search": "data analyst"},
            "headers": {"mcf-client": "jobseeker"},
            "timeout": 7.5,
        },
        {
            "url": API_LINK,
            "params": {"limit": 1, "page": 1, "search": "data analyst"},
            "headers": {"mcf-client": "jobseeker"},
            "timeout": 7.5,
        },
    ]


def test_careers_gov_client_rejects_limit_above_api_maximum() -> None:
    client = CareersGovClient(session=FakeSession([]), throttle_seconds=0)

    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        client.search_jobs(limit=101)
