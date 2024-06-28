import time
from argparse import ArgumentParser, Namespace
from contextlib import ExitStack
from dataclasses import dataclass
from functools import cached_property
from typing import Iterator, Sequence
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flatten_json import flatten as flatten_json  # type: ignore

from .api import Company, api_client
from .posting import Posting, posting_factory


@dataclass
class CareersPageParser:
    url: str

    @cached_property
    def page(self) -> requests.Response:
        response = requests.get(self.url, timeout=5)
        response.raise_for_status()
        return response

    @cached_property
    def links(self) -> Sequence[str]:
        links = []
        try:
            jd = self.page.json()
        except requests.exceptions.JSONDecodeError:
            pass
        else:
            for _, v in flatten_json(jd).items():
                if not isinstance(v, str):
                    continue
                if not v.startswith("https://"):
                    continue
                if v not in links:
                    links.append(v)
            return links
        for link in BeautifulSoup(self.page.text, "lxml").find_all("a"):
            if "href" not in link.attrs or not (href := link.attrs["href"]):
                continue
            href = urljoin(self.url, href)
            if "://" not in href:
                continue
            if href not in links:
                links.append(href)
        return links


class Scrape:
    def __init__(self) -> None:
        api_client.load_postings()

    @cached_property
    def args(self) -> Namespace:
        ap = ArgumentParser(description="Job posting scraper")
        ap.add_argument(
            "-u", "--url", dest="url", metavar="URL", help="Careers page URL"
        )
        ap.add_argument(
            "-c",
            "--company",
            dest="company",
            metavar="company",
            action="append",
            help=(
                "Name of company to include."
                " Can be specified multiple times."
                " (default: all companies included)"
            ),
        )
        ap.add_argument(
            "--csv",
            dest="csv",
            help="Path to Output CSV file for spreadsheet",
        )
        ap.add_argument(
            "-a",
            "--append",
            dest="csv_append",
            action="store_true",
            help="Append to CSV file instead of overwriting",
        )
        ap.add_argument(
            "-v",
            "--verbose",
            dest="verbose",
            action="store_true",
            help="Increase output verbosity",
        )
        return ap.parse_args()

    def __call__(self) -> None:
        with ExitStack() as es:
            csv = None
            if self.args.csv:
                csv = es.push(
                    open(  # noqa: SIM115
                        self.args.csv, "a" if self.args.csv_append else "w"
                    )
                )
            for posting in self.postings():
                if posting.pay_range is not None:
                    continue
                print(">>>", posting)
                if self.args.csv:
                    print(posting.csv_row, file=csv)

    def postings(self) -> Iterator[Posting]:
        for company, company_urls in self.generate_companies():
            print(
                f"Examining postings for {company}"
                f" ({', '.join(company_urls)})"
            )
            for company_url in company_urls:
                for url in self.page_urls(company_url):
                    if url in api_client.postings_by_url:
                        continue
                    if self.args.verbose:
                        print("Consider URL", url)
                    posting = posting_factory(url, company=company)
                    if not posting:
                        continue
                    if self.args.verbose:
                        print("Consider posting", posting)
                    time.sleep(0.05)
                    if not posting.remote:
                        continue
                    yield posting

    def generate_companies(self) -> Iterator[tuple[str, Sequence[str]]]:
        if self.args.company:
            for company in self.args.company:
                if self.args.url:
                    yield company, [self.args.url]
                else:
                    yield self.company_urls(company)
            return
        for company in api_client.companies_by_name.keys():
            yield self.company_urls(company)

    def company_urls(self, company: str) -> tuple[str, Sequence[str]]:
        def _c_urls(instance: Company) -> Sequence[str]:
            return [instance.careers_url] + (instance.careers_urls or [])

        try:
            return company, _c_urls(api_client.companies_by_name[company])
        except KeyError:
            raise Exception(f'No company "{company}" found')

    def page_urls(self, url: str) -> Sequence[str]:
        urls = []
        try:
            parser = CareersPageParser(url)
            for href in parser.links:
                if href in urls:
                    continue
                urls.append(href)
        except (requests.exceptions.HTTPError, Exception) as e:
            print(f"Unable to retrieve {url}, skipping ({e})")
        return urls
