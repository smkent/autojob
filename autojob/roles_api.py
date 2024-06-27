from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style  # type: ignore

from .api import API
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
class APIRoles:
    api: API = field(default_factory=API)
    resume: Path | None = None
    select_companies: set[str] = field(default_factory=set)
    skip_companies: set[str] = field(default_factory=set)
    check_duplicate_urls: bool = False
    save_posting: bool = True

    def __post_init__(self) -> None:
        # self.api.load_all()
        pass

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
        for role in self.role_gen():
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

    def role_gen(self) -> Iterator[Role]:
        role_counts = RoleCounter()

        for posting in self.api.postings_queue():
            yield Role(
                resume=self.resume,
                company=posting.company.name,
                role_title=posting.title,
                role_url=posting.url,
                role_job_board_urls=posting.job_board_urls,
                closed=bool(posting.closed),
                date_applied=None,
                sent_to_legal=None,
                role_num=role_counts.next(posting.company.name, None),
                save_posting=self.save_posting,
            )
