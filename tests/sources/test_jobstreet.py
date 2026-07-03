import pytest

from roleradar.ingestion.normalize_jobs import normalize_jobstreet_posting
from roleradar.sources.jobstreet import (
    JOBSTREET_HEADERS,
    JobStreetClient,
    parse_jobstreet_html,
    validate_jobstreet_url,
)

JOBSTREET_HTML = """
<html>
  <head>
    <title>Data Analyst job at Example Pte Ltd</title>
    <link rel="canonical" href="https://sg.jobstreet.com/job/123456" />
    <meta name="description" content="Fallback description" />
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "identifier": {"value": "seek-123456"},
        "title": "Data Analyst",
        "datePosted": "2026-07-01T01:02:03Z",
        "description": "<p>Python and SQL role.</p>",
        "hiringOrganization": {"name": "Example Pte Ltd"},
        "jobLocation": {
          "@type": "Place",
          "address": {
            "addressLocality": "Singapore",
            "addressCountry": "SG"
          }
        },
        "employmentType": "FULL_TIME",
        "baseSalary": {
          "@type": "MonetaryAmount",
          "currency": "SGD",
          "value": {
            "@type": "QuantitativeValue",
            "minValue": 5000,
            "maxValue": 7000,
            "unitText": "MONTH"
          }
        }
      }
    </script>
  </head>
  <body>Rendered content</body>
</html>
"""


class FakeResponse:
    text = JOBSTREET_HTML
    url = "https://sg.jobstreet.com/job/123456"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.request: tuple[str, dict[str, str], float] | None = None

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> FakeResponse:
        self.request = (url, headers, timeout)
        return FakeResponse()


def test_validate_jobstreet_url_accepts_jobstreet_hosts() -> None:
    assert (
        validate_jobstreet_url("https://sg.jobstreet.com/job/123456")
        == "https://sg.jobstreet.com/job/123456"
    )
    assert (
        validate_jobstreet_url("https://www.jobstreet.com.sg/job/123456")
        == "https://www.jobstreet.com.sg/job/123456"
    )


def test_parse_jobstreet_html_extracts_jobposting_json_ld() -> None:
    posting = parse_jobstreet_html(
        JOBSTREET_HTML,
        url="https://sg.jobstreet.com/job/123456",
    )

    assert posting["source_job_id"] == "seek-123456"
    assert posting["title"] == "Data Analyst"
    assert posting["company_name"] == "Example Pte Ltd"
    assert posting["canonical_url"] == "https://sg.jobstreet.com/job/123456"
    assert posting["location"] == "Singapore, SG"
    assert posting["workplace_type"] == "FULL_TIME"
    assert posting["description_text"] == "Python and SQL role."
    assert posting["salary_min"] == 5000.0
    assert posting["salary_max"] == 7000.0
    assert posting["salary_currency"] == "SGD"
    assert posting["salary_interval"] == "month"


def test_jobstreet_client_fetches_and_parses_single_posting() -> None:
    session = FakeSession()
    client = JobStreetClient(session=session, timeout_seconds=3.0)

    postings = client.fetch_postings("https://sg.jobstreet.com/job/123456")

    assert postings[0]["title"] == "Data Analyst"
    assert session.request == (
        "https://sg.jobstreet.com/job/123456",
        JOBSTREET_HEADERS,
        3.0,
    )


def test_normalize_jobstreet_posting_returns_ingestion_shape() -> None:
    posting = parse_jobstreet_html(
        JOBSTREET_HTML,
        url="https://sg.jobstreet.com/job/123456",
    )

    normalized = normalize_jobstreet_posting(posting)

    assert normalized.source == "jobstreet"
    assert normalized.source_job_id == "seek-123456"
    assert normalized.company_name == "Example Pte Ltd"
    assert normalized.title == "Data Analyst"
    assert normalized.description_text == "Python and SQL role."
    assert normalized.salary_min == 5000.0
    assert normalized.salary_max == 7000.0
    assert normalized.text_quality == "full_text"
