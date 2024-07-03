from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from colorama import Fore, Style  # type: ignore

from .api import Company, api_client
from .chrome_driver import Webdriver
from .exceptions import NextCompany
from .role import Role
from .utils import prompt_press_enter


@dataclass
class Roles:
    resume: Path | None = None
    select_companies: set[str] = field(default_factory=set)
    skip_companies: set[str] = field(default_factory=set)
    save_posting: bool = True
    chrome_driver: Webdriver = field(default_factory=Webdriver)

    def __post_init__(self) -> None:
        api_client.load_companies()

    def apply(self) -> None:
        webdriver = None
        with ExitStack() as es:
            skipping_company: Company | None = None
            for role, i, total in self.company_role_gen():
                try:
                    if skipping_company == role.posting.company:
                        continue
                    if not webdriver:
                        webdriver = es.enter_context(
                            self.chrome_driver(incognito=False)
                        )
                    role.webdriver = webdriver
                    role.print_info(
                        prefix=(
                            Style.BRIGHT
                            + Fore.YELLOW
                            + f"[{i}/{total}]"
                            + Style.RESET_ALL
                        )
                    )
                    role.apply()
                except NextCompany:
                    skipping_company = role.posting.company

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
                + company_roles[0].posting.company.name
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
            prev_company = company_roles[0].posting.company.name

    def companies_role_gen(self) -> Iterator[list[Role]]:
        company_roles: list[Role] = []
        for role in self.role_gen():
            if role.posting.closed:
                continue
            if role.role_path_has_activity:
                continue
            if role.similar_role_paths:
                role.print_info(compact=True)
                print(
                    "    Found existing directory match(es)"
                    f" for posting {role.posting.link}"
                )
                for srp in role.similar_role_paths:
                    print(f"        {srp.name}")
                print("")
                continue
            if (
                not company_roles
                or company_roles[0].posting.company.name
                == role.posting.company.name
            ):
                company_roles.append(role)
                continue
            yield company_roles
            company_roles = [role]
        if company_roles:
            yield company_roles

    def role_gen(self) -> Iterator[Role]:
        for posting in api_client.postings_queue():
            role = Role(
                posting=posting,
                resume=self.resume,
                save_posting=self.save_posting,
            )
            if self.select_companies and not (
                role.posting.company.name.lower() in self.select_companies
                or role.company_slug in self.select_companies
            ):
                continue
            if self.skip_companies and (
                role.posting.company.name.lower() in self.skip_companies
                or role.company_slug in self.skip_companies
            ):
                continue
            yield role
