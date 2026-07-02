from roleradar.ingestion.normalize_jobs import normalize_lever_posting


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

