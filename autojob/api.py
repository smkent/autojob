from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import dataclasses_json
import requests
from dataclasses_json.core import Json
from pandas import Series  # type: ignore
from pandas import Timestamp, read_excel

from .config import config
from .roles import Roles

dataclasses_json.cfg.global_config.encoders[datetime] = datetime.isoformat
dataclasses_json.cfg.global_config.decoders[datetime] = datetime.fromisoformat


def pdrow(row: Series, key: str, default: Any = None) -> Any:
    value = row[key] if row.notna()[key] else default
    if isinstance(value, Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        value = value.replace(microsecond=0)
        if not value.tzinfo:
            value = value.replace(tzinfo=timezone.utc)
    return value


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
    careers_urls: list[str] = field(default_factory=list)
    notes: str = ""
    pk: int | None = field(default=None, compare=False)
    link: str = field(default="", compare=False)

    @classmethod
    def from_dict(cls, kvs: Json, *args: Any, **kwargs: Any) -> Company:
        if isinstance(kvs, dict) and not kvs.get("careers_urls"):
            kvs["careers_urls"] = []
        return super().from_dict(kvs, *args, **kwargs)


@dataclass
class Posting(Model):
    company: Company
    url: str
    title: str
    location: str
    wa_jurisdiction: str = ""
    notes: str = ""
    job_board_urls: list[str] = field(default_factory=list)
    closed: datetime | None = None
    closed_note: str = ""
    pk: int | None = field(default=None, compare=False)
    link: str = field(default="", compare=False)

    @classmethod
    def from_dict(cls, kvs: Json, *args: Any, **kwargs: Any) -> Posting:
        if isinstance(kvs, dict) and not kvs.get("job_board_urls"):
            kvs["job_board_urls"] = []
        return super().from_dict(kvs, *args, **kwargs)


@dataclass
class Application(Model):
    posting: Posting
    applied: datetime = field(
        metadata=dataclasses_json.config(
            encoder=datetime.isoformat, decoder=datetime.fromisoformat
        )
    )
    reported: datetime | None = None
    bona_fide: int | None = None
    notes: str = ""
    pk: int | None = field(default=None, compare=False)
    link: str = field(default="", compare=False)


@dataclass
class API:
    companies_by_link: dict[str, Company] = field(default_factory=dict)
    companies_by_name: dict[str, Company] = field(default_factory=dict)
    postings_by_link: dict[str, Posting] = field(default_factory=dict)
    postings_by_url: dict[str, Posting] = field(default_factory=dict)
    applications_by_url: dict[str, Application] = field(default_factory=dict)

    api_limit: int = field(init=False, default=1000)

    def request_raw(
        self, url: str, method: str = "get", *args: Any, **kwargs: Any
    ) -> Any:
        kwargs.setdefault("headers", {})
        if data := kwargs.get("data"):
            if isinstance(data, dict):
                kwargs["data"] = json.dumps(data)
            kwargs["headers"]["Content-Type"] = "application/json"
        kwargs["headers"]["Authorization"] = f"Bearer {config.api_key}"
        if not url.startswith(config.api):
            url = config.api + url
        response = requests.request(method, url, *args, **kwargs)
        response.raise_for_status()
        return response

    def request(self, *args: Any, **kwargs: Any) -> Any:
        return self.request_raw(*args, **kwargs).json()

    def request_all(
        self,
        endpoint: str | None,
        method: str = "get",
        *args: Any,
        **kwargs: Any,
    ) -> Iterator[Any]:
        while endpoint:
            response = self.request_raw(endpoint)
            if next_url := response.links.get("next", {}).get("url"):
                endpoint = next_url
            else:
                endpoint = None
            yield from response.json()

    def load_all(self) -> None:
        self.load_companies()
        self.load_postings()
        self.load_applications()

    def load_companies(self) -> None:
        for data in self.request_all(f"companies?limit={self.api_limit}"):
            self.cache_company(Company.from_dict(data))

    def load_postings(self) -> None:
        for data in self.request_all(f"postings?limit={self.api_limit}"):
            data["company"] = self.get_company_by_link(data["company"])
            self.cache_posting(Posting.from_dict(data))

    def load_applications(self) -> None:
        for data in self.request_all(f"applications?limit={self.api_limit}"):
            data["posting"] = self.get_posting_by_link(data["posting"])
            self.cache_application(Application.from_dict(data))

    def cache_company(self, company: Company) -> None:
        self.companies_by_link[company.link] = company
        self.companies_by_name[company.name] = company

    def get_company_by_link(self, link: str) -> Company:
        if company := self.companies_by_link.get(link):
            return company
        data = self.request(link)
        return Company.from_dict(data)

    def get_company_by_name(self, name: str) -> Company:
        if company := self.companies_by_name.get(name):
            return company
        data = self.request(f"companies/by_name/{name}")
        return Company.from_dict(data)

    def save_company(self, company: Company) -> Company:
        url = company.link if company.link else "companies"
        method = "put" if company.link else "post"
        company_dict = company.to_dict()
        data = self.request(url, method=method, data=company_dict)
        saved_company = Company.from_dict(data)
        assert saved_company.link
        self.cache_company(saved_company)
        return saved_company

    def get_posting_by_link(self, link: str) -> Posting:
        if posting := self.postings_by_link.get(link):
            return posting
        data = self.request(link)
        data["company"] = self.get_company_by_link(data["company"])
        return Posting.from_dict(data)

    def get_posting_by_url(self, url: str) -> Posting:
        if posting := self.postings_by_url.get(url):
            return posting
        data = self.request(f"postings/by_url/{quote(url)}")
        data["company"] = self.get_company_by_link(data["company"])
        return Posting.from_dict(data)

    def save_posting(self, posting: Posting) -> Posting:
        url = posting.link if posting.link else "postings"
        method = "put" if posting.link else "post"
        posting_dict = posting.to_dict()
        assert isinstance(posting_dict["company"], dict)
        posting_dict["company"] = posting_dict["company"]["link"]
        data = self.request(url, method=method, data=posting_dict)
        data["company"] = self.get_company_by_link(data["company"])
        saved_posting = Posting.from_dict(data)
        assert saved_posting.link
        self.cache_posting(saved_posting)
        return saved_posting

    def cache_posting(self, posting: Posting) -> None:
        self.postings_by_link[posting.link] = posting
        self.postings_by_url[posting.url] = posting

    def get_application_by_url(self, url: str) -> Application:
        if application := self.applications_by_url.get(url):
            return application
        data = self.request(f"applications/by_url/{quote(url)}")
        data["posting"] = self.get_posting_by_link(data["posting"])
        return Application.from_dict(data)

    def save_application(self, application: Application) -> Application:
        url = application.link if application.link else "postings"
        method = "put" if application.link else "post"
        application_dict = application.to_dict()
        assert isinstance(application_dict["posting"], dict)
        application_dict["posting"] = application_dict["posting"]["link"]
        data = self.request(url, method=method, data=application_dict)
        data["posting"] = self.get_posting_by_link(data["posting"])
        saved_application = Application.from_dict(data)
        assert saved_application.link
        self.cache_application(application)
        return saved_application

    def cache_application(self, application: Application) -> None:
        self.applications_by_url[application.posting.url] = application


@dataclass
class SpreadsheetData:
    roles: Roles
    api: API = field(default_factory=API)

    def migrate_to_api(self) -> None:
        self.api.load_all()
        self.migrate_companies_to_api()
        self.migrate_postings_to_api()
        self.migrate_applications_to_api()

    def migrate_companies_to_api(self) -> None:
        for company in self.companies_gen():
            try:
                existing_company = self.api.get_company_by_name(company.name)
                if company == existing_company:
                    continue
                company.link = existing_company.link
                print(f"Company {company.name} differs")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code != 404:
                    raise
                print(f"Adding company {company.name}")
            try:
                self.api.save_company(company)
            except Exception as e:
                print(f"Error saving company {company}: {e}")

    def migrate_postings_to_api(self) -> None:
        for posting in self.postings_gen():
            try:
                existing_posting = self.api.get_posting_by_url(posting.url)
                if existing_posting.closed and posting.closed:
                    posting.closed = existing_posting.closed
                if posting == existing_posting:
                    continue
                posting.link = existing_posting.link
                print(f"Posting {posting.url} differs")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code != 404:
                    raise
                print(f"Adding posting {posting.company.name} / {posting.url}")
            try:
                self.api.save_posting(posting)
            except Exception as e:
                print(f"Error adding posting {posting}: {e}")

    def migrate_applications_to_api(self) -> None:
        for application in self.applications_gen():
            try:
                existing_application = self.api.get_application_by_url(
                    application.posting.url
                )
                if application == existing_application:
                    continue
                application.link = existing_application.link
                print(
                    f"Application for {application.posting.company.name}"
                    f" / {application.posting.url} differs"
                )
            except requests.exceptions.HTTPError as e:
                if e.response.status_code != 404:
                    raise
                print(
                    "Adding application for"
                    f" {application.posting.company.name}"
                    f" / {application.posting.url}"
                )
            try:
                self.api.save_application(application)
            except Exception as e:
                print(f"Error adding application {application}: {e}")

    def companies_gen(self) -> Iterator[Company]:
        df = read_excel(
            config.spreadsheet,
            "Companies",
        )
        for row_idx in range(0, len(df)):
            row = df.iloc[row_idx]
            carray = row["Careers Pages"].strip().split(", ")
            careers_url = carray.pop(0)
            if cmore := pdrow(row, "Additional Careers URLs", ""):
                carray += cmore.split(", ")
            yield Company(
                name=str(row["Company"]).strip(),
                hq=row["HQ location"],
                url=row["URL"],
                careers_url=careers_url,
                careers_urls=carray,
                employees_est=str(row["# Employees"]),
                employees_est_source=row["# Employees Source"],
                how_found=row["How Found"],
                notes=row["Notes"] if row.notna()["Notes"] else "",
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
            if more_urls := pdrow(row, "Job Board URL", ""):
                more_urls = [
                    u.strip() for u in more_urls.strip().split(os.linesep)
                ]
            yield Posting(
                company=self.api.get_company_by_name(
                    str(row["Company"]).strip()
                ),
                url=row["Role Posting URL"],
                job_board_urls=more_urls or [],
                title=row["Role Title"].strip(),
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

    def applications_gen(self) -> Iterator[Application]:
        df = read_excel(
            config.spreadsheet,
            config.spreadsheet_tab,
            skiprows=lambda x: x in [1],
        )
        for row_idx in range(0, len(df)):
            row = df.iloc[row_idx]
            applied = pdrow(row, "Date Applied")
            if not applied:
                continue
            yield Application(
                posting=self.api.get_posting_by_url(row["Role Posting URL"]),
                applied=applied,
                reported=pdrow(row, "Sent to Legal"),
                bona_fide=int(pdrow(row, "Bona fide rtg.", 0)) or None,
                notes=pdrow(row, "Personal notes", ""),
            )
