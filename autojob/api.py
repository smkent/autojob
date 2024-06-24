from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from typing import Any

import dataclasses_json
import requests
from pandas import read_excel  # type: ignore

from .config import config
from .roles import Roles


def model_exclude(value: Any) -> bool:
    if isinstance(value, str):
        return value == ""
    return value is None


class Model(dataclasses_json.DataClassJsonMixin):
    dataclass_json_config = dataclasses_json.config(
        undefined=dataclasses_json.Undefined.EXCLUDE, exclude=model_exclude
    )["dataclasses_json"]


@dataclass
class Company(Model):
    name: str
    hq: str
    url: str
    careers_url: str
    employees_est: str
    employees_est_source: str
    how_found: str
    notes: str = ""
    pk: int | None = None
    link: str = ""


@dataclass
class Posting(Model):
    company: Company
    url: str
    title: str
    location: str
    wa_jurisdiction: str = ""
    notes: str = ""
    closed: datetime | None = field(
        default=None,
        metadata=dataclasses_json.config(
            encoder=datetime.isoformat, decoder=datetime.fromisoformat
        ),
    )
    closed_note: str = ""
    pk: int | None = None
    link: str = ""


class API:
    def request(
        self, url: str, method: str = "get", *args: Any, **kwargs: Any
    ) -> Any:
        kwargs.setdefault("headers", {})
        kwargs["headers"]["Authorization"] = f"Bearer {config.api_key}"
        response = requests.request(method, config.api + url, *args, **kwargs)
        response.raise_for_status()
        return response.json()

    @cache  # noqa
    def get_company(self, pk: int) -> Company:
        data = self.request(f"companies/{pk}")
        return Company(**data)

    @cache  # noqa
    def get_company_by_name(self, name: str) -> Company:
        data = self.request(f"companies/by_name/{name}")
        return Company(**data)

    def add_company(self, company: Company) -> None:
        company_dict = company.__dict__
        company_dict.pop("pk")
        company_dict.pop("link")
        self.request("companies", method="post", data=company_dict)

    def add_posting(self, posting: Posting) -> None:
        posting_dict = posting.__dict__.copy()
        posting_dict.pop("pk")
        posting_dict.pop("link")
        posting_dict["company"] = posting_dict["company"].link
        if posting_dict["closed"]:
            posting_dict["closed"] = (
                posting_dict["closed"].replace(microsecond=0).isoformat()
            )
        self.request("postings", method="post", data=posting_dict)


@dataclass
class SpreadsheetData:
    roles: Roles
    api: API = field(default_factory=API)

    def migrate_to_api(self) -> None:
        self.migrate_companies_to_api()
        self.migrate_postings_to_api()

    def migrate_companies_to_api(self) -> None:
        for company in self.companies_gen():
            print(f"Adding company {company.name}")
            if ", " in company.careers_url:
                print("Warning: dropping additional careers page URLs")
                company.careers_url = company.careers_url.split(", ", 1)[0]
            try:
                self.api.add_company(company)
            except Exception as e:
                print(f"Error adding company {company}: {e}")

    def migrate_postings_to_api(self) -> None:
        for posting in self.postings_gen():
            company_name = (
                posting.company.name
                if posting.company
                else str(posting.company_name or "")
            )
            print(f"Adding posting {company_name} / {posting.url}")
            try:
                self.api.add_posting(posting)
            except Exception as e:
                print(f"Error adding posting {posting}: {e}")

    def companies_gen(self) -> Iterator[Company]:
        df = read_excel(
            config.spreadsheet,
            "Companies",
        )
        for row_idx in range(0, len(df)):
            row = df.iloc[row_idx]
            yield Company(
                row["Company"],
                row["HQ location"],
                row["URL"],
                row["Careers Pages"],
                row["# Employees"],
                row["# Employees Source"],
                row["How Found"],
                row["Notes"] if row.notna()["Notes"] else "",
            )

    def postings_gen(self) -> Iterator[Posting]:
        df = read_excel(
            config.spreadsheet,
            "Postings",
            skiprows=lambda x: x in [1],
        )
        for row_idx in range(0, len(df)):
            row = df.iloc[row_idx]
            closed_note = row["Closed"] if row.notna()["Closed"] else ""
            closed = (
                datetime.now().replace(microsecond=0) if closed_note else None
            )
            if closed_note in {"x", "z"}:
                closed_note = ""
            yield Posting(
                company=self.api.get_company_by_name(row["Company"]),
                url=row["Role Posting URL"],
                title=row["Role Title"],
                location=row["Role Location"],
                wa_jurisdiction=(
                    row["WA jurisdiction if remote"]
                    if row.notna()["WA jurisdiction if remote"]
                    else ""
                ),
                notes=(
                    row["Notes/evidence"]
                    if row.notna()["Notes/evidence"]
                    else ""
                ),
                closed=closed,
                closed_note=closed_note,
            )
