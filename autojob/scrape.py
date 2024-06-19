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
from pandas import DataFrame  # type: ignore

from .posting import Posting, posting_factory
from .spreadsheet import Spreadsheet


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
                "Name of company in spreadsheet to include."
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
                    try:
                        df = self.postings_sheet.loc[
                            self.postings_sheet["Role Posting URL"].str.match(
                                url, na=False
                            )
                        ]
                    except Exception as e:
                        print(f"Error checking if {url} exists: {e}")
                        continue
                    if not df.empty:
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
        for row in self.companies_sheet.iterrows():
            row_data = self.companies_sheet.iloc[row[0]]
            yield self.company_row_to_urls(row_data)

    def company_urls(self, company: str) -> tuple[str, Sequence[str]]:
        df = self.companies_sheet.loc[
            self.companies_sheet["Company"].str.match(
                company.lower(), na=False, case=False
            )
        ]
        if df["Company"].count() < 1:
            raise Exception(f"No spreadsheet row found for {company}")
        for row in df.iterrows():
            row_data = self.companies_sheet.iloc[row[0]]
            return self.company_row_to_urls(row_data)
        raise Exception(f"No careers page URL found for {company}")

    def company_row_to_urls(self, row: DataFrame) -> tuple[str, Sequence[str]]:
        urls = [row["Careers Pages"]]
        if (additional_urls := row["Additional Careers URLs"]) and isinstance(
            additional_urls, str
        ):
            urls += [u.strip() for u in additional_urls.split(",")]
        return row["Company"], urls

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

    @cached_property
    def companies_sheet(self) -> DataFrame:
        return Spreadsheet.sheet("Companies")

    @cached_property
    def postings_sheet(self) -> DataFrame:
        return Spreadsheet.sheet("Postings")
