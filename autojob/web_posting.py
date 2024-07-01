from __future__ import annotations

import re
from contextlib import suppress
from functools import cached_property

import requests
from bs4 import BeautifulSoup

from .utils import url_to_soup

PAY_PATTERNS = [r"(\$[0-9,]*)"]
MATCH_LOCATIONS = {
    "remote - united states",
    "remote - us",
    "remote, united states",
    "remote, us",
    "united states of america",
    "united states",
    "us remote",
}
SKIP_LOCATIONS = {
    "australia",
    "berlin",
    "brussels",
    "canada",
    "china",
    "colombia",
    "europe",
    "germany",
    "haryana",
    "india",
    "jamaica",
    "japan",
    "latam",
    "london",
    "luxembourg",
    "mexico",
    "monetral",
    "netherlands",
    "pakistan",
    "philippines",
    "poland",
    "pune",
    "singapore",
    "south africa",
    "sydney",
    "tel aviv",
    "toronto",
    "united kingdom",
}
MIN_NUM = 100
MAX_NUM = 990_000


def web_posting_factory(
    url: str, company: str | None = None
) -> WebPosting | None:
    def _posting_class(url: str) -> type[WebPosting] | None:
        if (
            re.search(r"://boards(\.eu)?\.greenhouse\.io", url)
            or "gh_jid=" in url
        ):
            return GreenhousePosting
        if re.search(r"://jobs(\.eu)?\.lever\.co", url) and re.search(
            r"[0-9a-fA-f-]{36}$", url
        ):
            return LeverPosting
        return None

    if posting_class := _posting_class(url):
        with suppress(requests.exceptions.HTTPError):
            posting = posting_class(url, company)
            try:
                assert str(posting)
                if "talent community" in posting.title.lower():
                    return None
            except Exception as e:
                print(f"Skip {url}: {e}")
                return None
            return posting
    return None


class WebPosting:
    def __init__(self, url: str, company: str | None = None) -> None:
        self.url = url
        if company:
            self.company = company

    def __repr__(self) -> str:
        remote_str = " (remote)" if self.remote else ""
        pay_str = ""
        if self.pay_range:
            pay_str = (
                f" (${self.pay_range[0]:,}"  # noqa: E203, E231
                f" - ${self.pay_range[1]:,})"  # noqa: E203, E231
            )
        return (
            f"<{self.__class__.__name__}: {self.company}"
            f" / {self.title} / {self.locations}{remote_str}{pay_str}>"
        )

    @property
    def csv_row(self) -> str:
        location_str = ("Remote, " if self.remote else "") + (
            ", ".join(self.locations) if self.locations else ""
        )
        return ",".join(
            f'"{i}"'
            for i in [self.company, "", self.url, self.title, "", location_str]
        )

    @cached_property
    def soup(self) -> BeautifulSoup:
        return url_to_soup(self.url)

    @cached_property
    def remote(self) -> bool:
        if not self.locations:
            return False
        if MATCH_LOCATIONS & set(self.locations):
            return True
        for location in self.locations:
            for skip_location in SKIP_LOCATIONS:
                if skip_location.lower() in location.lower():
                    return False
                    # continue
            if "remote" in location.lower():
                return True
        page_words = {w.strip().lower() for w in self.soup.text.split()}
        if {"remote", "remotely"} & page_words:
            return True
        if {"hybrid", "onsite", "on-site"} & page_words:
            return False
        return False

    @cached_property
    def pay_range(self) -> tuple[int, int] | None:
        def _parse_num(raw: str) -> int | None:
            raw_strip = re.sub(r"[$,]", "", raw.strip())
            if raw_strip[-1].lower() == "k":
                raw_strip = raw_strip[:-1] + "000"
            try:
                return int(raw_strip)
            except Exception:
                return None

        all_text = " ".join([el.text for el in self.soup.find_all(text=True)])
        all_nums = set()
        for pattern in PAY_PATTERNS:
            for m in re.findall(pattern, all_text):
                if num := _parse_num(m):
                    if num < MIN_NUM or num > MAX_NUM:
                        continue
                    all_nums.add(num)
        if not all_nums:
            return None
        return (min(all_nums), max(all_nums))

    @cached_property
    def company(self) -> str:
        raise NotImplementedError()

    @cached_property
    def title(self) -> str:
        raise NotImplementedError()

    @cached_property
    def locations(self) -> list[str]:
        raise NotImplementedError()


class GreenhousePosting(WebPosting):
    @cached_property
    def title(self) -> str:
        for el in self.soup.find_all("h1", {"class": "app-title"}):
            if el.text:
                return str(el.text).strip()
        raise Exception("Unable to determine role title in posting", self.url)

    @cached_property
    def locations(self) -> list[str]:
        for el in self.soup.find_all("div", {"class": "location"}):
            if el.text:
                if "•" in el.text:
                    return [i.strip() for i in el.text.split("•")]
                return [str(el.text).strip()]
        return []


class LeverPosting(WebPosting):
    @cached_property
    def title(self) -> str:
        for el in self.soup.find_all("h2"):
            if el.text:
                return str(el.text).strip()
        raise Exception("Unable to determine role title in posting", self.url)

    @cached_property
    def locations(self) -> list[str]:
        for el in self.soup.find_all("div", {"class": "location"}):
            if el.text:
                if "/" in el.text:
                    return [i.strip() for i in el.text.split("/")]
                return [str(el.text).strip()]
        raise Exception(
            "Unable to determine role location in posting", self.url
        )
