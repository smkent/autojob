from typing import Any


def make_session_response() -> dict[str, Any]:
    return {
        "username": "vader",
    }


def make_companies_response() -> list[dict[str, Any]]:
    return [
        {
            "pk": 1,
            "link": "https://api.example.com/companies/1",
            "name": "Initech",
            "hq": "Everytown, USA",
            "url": "https://initech.example.com",
            "careers_url": "https://careers.initech.example.com",
            "employees_est": "15",
            "employees_est_source": "LinkedIn company page",
            "how_found": "LinkedIn",
        }
    ]


def make_queue_response() -> list[dict[str, Any]]:
    return [
        {
            "pk": 10,
            "link": "https://api.example.com/postings/10",
            "company": "https://api.example.com/companies/1",
            "url": "https://careers.example.com/jobs/1",
            "title": "Principal Senior Staff Executive Delivery Boy",
            "location": "Remote",
        }
    ]
