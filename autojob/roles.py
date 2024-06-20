from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property
from pathlib import Path

from colorama import Fore, Style  # type: ignore
from pandas import Series  # type: ignore
from pandas import read_excel

from .config import config
from .role import Role
from .utils import prompt_press_enter


class RoleCounter:
    def __init__(self) -> None:
        self.counts: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    def next(self, company: str, date: datetime | None = None) -> int:
        date_str = (date or datetime.now()).strftime("%Y%m%d")
        self.counts[date_str][company] += 1
        return self.counts[date_str][company]


@dataclass
class Roles:
    resume: Path | None = None
    select_companies: set[str] = field(default_factory=set)
    skip_companies: set[str] = field(default_factory=set)
    check_duplicate_urls: bool = False
    save_posting: bool = True

    @staticmethod
    def role_apply_today(r: Series) -> bool:
        if r.notna()["Closed"]:
            return False
        if not r.notna()["Date Applied"]:
            return True
        da = r["Date Applied"].to_pydatetime()
        assert isinstance(da, datetime)
        return da.date() == date.today()

    @cached_property
    def role_dupes_check(self) -> bool:
        dupes = False
        all_urls: set[str] = set()
        df = read_excel(config.spreadsheet, config.spreadsheet_tab)
        for row_idx in range(0, len(df)):
            row = df.iloc[row_idx]
            check_urls = []
            if row.notna()["Role Posting URL"] and (
                url := row["Role Posting URL"]
            ):
                check_urls.append(url)
            if row.notna()["Job Board URL"] and (
                value := row["Job Board URL"]
            ):
                for url in value.strip().split(os.linesep):
                    check_urls.append(url)
            for url in check_urls:
                if url in all_urls:
                    print(f"Duplicate role URL: {url}")
                    dupes = True
                all_urls.add(url)
        return dupes

    def apply(self) -> None:
        for role, i, total in self.company_role_gen():
            role.print_info(
                prefix=(
                    Style.BRIGHT
                    + Fore.YELLOW
                    + f"[{i}/{total}]"
                    + Style.RESET_ALL
                )
            )
            role.apply()

    def company_role_gen(self) -> Iterator[tuple[Role, int, int]]:
        prev_company = None
        company_roles: list[Role] = []
        for company_roles in self.companies_role_gen():
            print(
                Style.BRIGHT
                + Fore.GREEN
                + ">>> "
                + Style.RESET_ALL
                + ("Switching to" if prev_company else "Starting with")
                + " company "
                + Style.BRIGHT
                + company_roles[0].company
                + Style.RESET_ALL
                + Style.BRIGHT
                + Fore.YELLOW
                + f" ({len(company_roles)} roles)"
                + Style.RESET_ALL
            )
            print("")
            prompt_press_enter()
            for i, company_role in enumerate(company_roles):
                yield company_role, i + 1, len(company_roles)
            prev_company = company_roles[0].company

    def companies_role_gen(self) -> Iterator[list[Role]]:
        company_roles: list[Role] = []
        for role in self.role_gen(self.role_apply_today):
            if role.closed:
                continue
            if role.role_path_has_activity:
                continue
            if not company_roles or company_roles[0].company == role.company:
                company_roles.append(role)
                continue
            yield company_roles
            company_roles = [role]
        if company_roles:
            yield company_roles

    def role_gen(
        self, row_filter: Callable[[Series], bool] | None = None
    ) -> Iterator[Role]:
        if self.check_duplicate_urls:
            assert not self.role_dupes_check
        role_counts = RoleCounter()
        df = read_excel(
            config.spreadsheet,
            config.spreadsheet_tab,
            skiprows=lambda x: x in [1],
        )
        for row_idx in range(0, len(df)):
            row = df.iloc[row_idx]
            if row_filter and not row_filter(row):
                continue
            if (
                not row["Company"]
                or not row["Role Posting URL"]
                or not row["Role Title"]
            ):
                continue
            role = Role.from_spreadsheet_row(
                row,
                self.resume,
                role_num=role_counts.next(
                    row["Company"],
                    (
                        row["Date Applied"].to_pydatetime()
                        if row.notna()["Date Applied"]
                        else None
                    ),
                ),
                save_posting=self.save_posting,
            )
            if self.select_companies and not (
                role.company.lower() in self.select_companies
                or role.company_slug in self.select_companies
            ):
                continue
            if self.skip_companies and (
                role.company.lower() in self.skip_companies
                or role.company_slug in self.skip_companies
            ):
                continue
            yield role
