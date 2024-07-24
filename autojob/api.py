from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import cached_property
from typing import Any
from urllib.parse import quote

import dataclasses_json
import requests
from dataclasses_json.core import Json

from .config import config

dataclasses_json.cfg.global_config.encoders[datetime] = datetime.isoformat
dataclasses_json.cfg.global_config.decoders[datetime] = datetime.fromisoformat


class CompanyPriority(int, Enum):
    desc: str

    def __new__(cls, value: int, desc: str) -> CompanyPriority:
        member = int.__new__(cls, value)
        member._value_ = value
        member.desc = desc
        return member

    HIGH = 1000, "High"
    NORMAL = 500, "Normal"
    LOW = 100, "Low"


def model_exclude(value: Any) -> bool:
    if isinstance(value, str):
        return value == ""
    return value is None


class Model(dataclasses_json.DataClassJsonMixin):
    dataclass_json_config = dataclasses_json.config(
        undefined=dataclasses_json.Undefined.EXCLUDE, exclude=model_exclude
    )["dataclasses_json"]


@dataclass
class User(Model):
    pk: int
    username: str
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


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
    in_wa: bool
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
    applied: datetime | None = None
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

    company_priority: CompanyPriority | None = None
    in_wa: bool | None = None

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
        if not url.startswith(config.api_url):
            url = config.api_url + url
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
            response = self.request_raw(endpoint, *args, **kwargs)
            if next_url := response.links.get("next", {}).get("url"):
                endpoint = next_url
            else:
                endpoint = None
            yield from response.json()

    @cached_property
    def me(self) -> User:
        return User.from_dict(self.request("me", method="get"))

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

    def postings_queue(self) -> Iterator[Posting]:
        params = {"limit": str(self.api_limit)}
        if self.company_priority is not None:
            params["priority"] = self.company_priority.value
        if self.in_wa is not None:
            params["in_wa"] = str(self.in_wa).lower()
        for data in self.request_all("queue", params=params):
            data["company"] = self.get_company_by_link(data["company"])
            yield Posting.from_dict(data)

    def cache_company(self, company: Company) -> None:
        self.companies_by_link[company.link] = company
        self.companies_by_name[company.name] = company

    def get_company_by_link(self, link: str) -> Company:
        if company := self.companies_by_link.get(link):
            return company
        data = self.request(link)
        company = Company.from_dict(data)
        self.cache_company(company)
        return company

    def get_company_by_name(self, name: str) -> Company:
        if company := self.companies_by_name.get(name):
            return company
        data = self.request(f"companies/by_name/{name}")
        company = Company.from_dict(data)
        self.cache_company(company)
        return company

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
        posting = Posting.from_dict(data)
        self.cache_posting(posting)
        return posting

    def get_posting_by_url(self, url: str) -> Posting:
        if posting := self.postings_by_url.get(url):
            return posting
        data = self.request(f"postings/by_url/{quote(url)}")
        data["company"] = self.get_company_by_link(data["company"])
        posting = Posting.from_dict(data)
        self.cache_posting(posting)
        return posting

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
        application = Application.from_dict(data)
        self.cache_application(application)
        return application

    def save_application(self, application: Application) -> Application:
        url = application.link if application.link else "applications"
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


api_client = API()
