from roleradar.ingestion.normalize_jobs import (
    normalize_adzuna_posting,
    normalize_careers_gov_posting,
    normalize_greenhouse_posting,
    normalize_jobstreet_posting,
    normalize_lever_posting,
)


def test_normalize_lever_posting_extracts_description_and_salary() -> None:
    posting = {
        "id": "abc123",
        "text": "Data Analyst",
        "hostedUrl": "https://jobs.lever.co/example/abc123",
        "createdAt": 1_700_000_000_000,
        "categories": {"location": "Singapore", "commitment": "Full-time"},
        "descriptionPlain": "Use Python and SQL.",
        "lists": [{"text": "Responsibilities", "content": "Build dashboards."}],
        "salaryRange": {
            "min": 5000,
            "max": 7000,
            "currency": "SGD",
            "interval": "month",
        },
    }

    normalized = normalize_lever_posting(
        posting=posting,
        company_name="Example Pte Ltd",
        board_token_or_site="example",
    )

    assert normalized.source == "lever"
    assert normalized.source_job_id == "example:abc123"
    assert normalized.title == "Data Analyst"
    assert normalized.location == "Singapore"
    assert normalized.salary_min == 5000
    assert normalized.salary_max == 7000
    assert normalized.salary_currency == "SGD"
    assert "Build dashboards" in normalized.description_text
    assert normalized.content_hash is not None


def test_normalize_greenhouse_posting_extracts_content_text() -> None:
    posting = {
        "id": 123,
        "title": "Data Analyst",
        "absolute_url": "https://boards.greenhouse.io/example/jobs/123",
        "location": {"name": "Singapore"},
        "content": "<p>Use Python and SQL.</p><ul><li>Build dashboards.</li></ul>",
        "updated_at": "2026-07-01T01:02:03Z",
    }

    normalized = normalize_greenhouse_posting(
        posting=posting,
        company_name="Example Pte Ltd",
        board_token_or_site="example",
    )

    assert normalized.source == "greenhouse"
    assert normalized.source_job_id == "example:123"
    assert normalized.title == "Data Analyst"
    assert normalized.location == "Singapore"
    assert normalized.description_text == "Use Python and SQL. Build dashboards."
    assert normalized.content_hash is not None
    assert normalized.source_updated_at is not None


def test_normalize_greenhouse_posting_extracts_pay_input_ranges() -> None:
    posting = {
        "id": 123,
        "title": "Data Analyst",
        "absolute_url": "https://boards.greenhouse.io/example/jobs/123",
        "location": {"name": "Singapore"},
        "content": "<p>Use Python and SQL.</p>",
        "pay_input_ranges": [
            {
                "min_value": 60000,
                "max_value": 90000,
                "currency": "SGD",
                "unit": "year",
            }
        ],
    }

    normalized = normalize_greenhouse_posting(
        posting=posting,
        company_name="Example Pte Ltd",
        board_token_or_site="example",
    )

    assert normalized.salary_min == 60000
    assert normalized.salary_max == 90000
    assert normalized.salary_currency == "SGD"
    assert normalized.salary_interval == "yearly"


def test_normalize_adzuna_posting_marks_description_as_snippet() -> None:
    posting = {
        "id": "adzuna-1",
        "title": "Data Analyst",
        "redirect_url": "https://www.adzuna.sg/jobs/details/adzuna-1",
        "description": "Python and SQL snippet...",
        "created": "2026-07-01T01:02:03Z",
        "salary_min": 5000,
        "salary_max": 7000,
        "company": {"display_name": "Example Pte Ltd"},
        "location": {"display_name": "Singapore"},
        "contract_time": "full_time",
    }

    normalized = normalize_adzuna_posting(posting)

    assert normalized.source == "adzuna"
    assert normalized.source_job_id == "adzuna-1"
    assert normalized.company_name == "Example Pte Ltd"
    assert normalized.description_text == "Python and SQL snippet..."
    assert normalized.text_quality == "snippet"
    assert normalized.raw_payload["text_quality"] == "snippet"
    assert normalized.salary_min == 5000
    assert normalized.salary_max == 7000
    assert normalized.salary_currency is None


def test_normalize_careers_gov_posting_extracts_api_fields() -> None:
    posting = {
        "uuid": "mcf-1",
        "metadata": {
            "jobPostId": "post-1",
            "updatedAt": "2026-07-01T01:02:03Z",
        },
        "title": "Data Analyst",
        "description": (
            "<h2>Responsibilities</h2>"
            "<p>Support data mapping between Salesforce and external systems.</p>"
            "<h2>Required competencies and certifications</h2>"
            "<p>Minimum 4 years of experience in data analysis.</p>"
            "<h2>Preferred competencies and qualifications</h2>"
            "<p>Interest or exposure to Salesforce.</p>"
        ),
        "postedCompany": {"name": "Example Pte Ltd"},
        "salary": {
            "minimum": 5000,
            "maximum": 7000,
            "type": {"salaryType": "Monthly"},
        },
        "employmentTypes": [{"employmentType": "Full Time"}],
        "_links": {
            "self": {
                "href": "https://api1.mycareersfuture.sg/v2/jobs/mcf-1",
            }
        },
    }

    normalized = normalize_careers_gov_posting(posting)

    assert normalized.source == "careers_gov"
    assert normalized.source_job_id == "mcf-1"
    assert normalized.company_name == "Example Pte Ltd"
    assert "Support data mapping" in normalized.description_text
    assert normalized.salary_min == 5000
    assert normalized.salary_max == 7000
    assert normalized.salary_currency == "SGD"
    assert normalized.salary_interval == "Monthly"
    assert normalized.workplace_type == "Full Time"
    assert normalized.source_updated_at is not None
    assert normalized.raw_payload["source_api"] == "mycareersfuture"
    assert (
        normalized.raw_payload["structured_sections"]["responsibilities"]
        == "Support data mapping between Salesforce and external systems."
    )
    assert (
        normalized.raw_payload["structured_sections"][
            "required_competencies_and_certifications"
        ]
        == "Minimum 4 years of experience in data analysis."
    )
    assert (
        normalized.raw_payload["structured_sections"][
            "preferred_competencies_and_qualifications"
        ]
        == "Interest or exposure to Salesforce."
    )


def test_normalize_jobstreet_posting_extracts_search_result_fields() -> None:
    posting = {
        "id": "jobstreet-1",
        "title": "Data Analyst",
        "jobUrl": "/job/123",
        "companyName": "Example Pte Ltd",
        "locations": [{"label": "Singapore"}],
        "workTypes": [{"label": "Full time"}],
        "teaser": "Use Python and SQL.",
        "bulletPoints": ["Build dashboards."],
        "salaryLabel": "$5,000 - $7,000 per month",
        "listingDate": "2026-07-01T01:02:03Z",
    }

    normalized = normalize_jobstreet_posting(posting)

    assert normalized.source == "jobstreet"
    assert normalized.source_job_id == "jobstreet-1"
    assert normalized.company_name == "Example Pte Ltd"
    assert normalized.title == "Data Analyst"
    assert normalized.canonical_url == "https://www.jobstreet.com.sg/job/123"
    assert normalized.location == "Singapore"
    assert normalized.workplace_type == "Full time"
    assert "Build dashboards" in normalized.description_text
    assert normalized.salary_min == 5000
    assert normalized.salary_max == 7000
    assert normalized.salary_currency == "SGD"
    assert normalized.salary_interval == "monthly"
    assert normalized.text_quality == "snippet"
    assert normalized.source_updated_at is not None
    assert normalized.raw_payload["source_api"] == "jobstreet_chalice_search"
