from __future__ import annotations

import os
import shutil
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from pathlib import Path

from colorama import Fore, Style  # type: ignore
from pandas import Series  # type: ignore
from pypdf import PdfReader
from slugify import slugify

from .chrome_driver import Webdriver, WebdriverPage
from .config import config

chrome_driver = Webdriver()


class ApplyAction(StrEnum):
    desc: str

    def __new__(cls, value: str, desc: str = "") -> ApplyAction:
        member = str.__new__(cls, value)
        member._value_ = value
        member.desc = desc
        return member

    APPLICATION_PAGE = "a", "Save application PDF"
    APPLICATION_SUBMITTED = "s", "Save application submitted PDF"
    FINISH_ROLE = "n", "Next role"
    QUIT = "q", "Quit"


@dataclass
class RoleChecks:
    email_confirmation: bool = False

    @property
    def passed(self) -> bool:
        return all([getattr(self, field.name) for field in fields(self)])

    @property
    def failed(self) -> list[str]:
        return sorted(
            [
                field.name
                for field in fields(self)
                if not getattr(self, field.name)
            ]
        )


@dataclass
class Role:
    resume: Path
    company: str
    role_title: str
    role_url: str
    role_job_board_urls: list[str] = field(default_factory=list)
    closed: bool = False
    date_applied: datetime | None = None
    sent_to_legal: datetime | None = None
    role_num: int = 0
    save_posting: bool = False
    saved_file_counts: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )

    @staticmethod
    def from_spreadsheet_row(
        resume: Path,
        row: Series,
        role_num: int = 0,
        save_posting: bool = False,
    ) -> Role:
        return Role(
            resume=resume,
            company=row["Company"],
            role_title=row["Role Title"],
            role_url=row["Role Posting URL"],
            role_job_board_urls=(
                row["Job Board URL"].strip().split(os.linesep)
                if row.notna()["Job Board URL"] and row["Job Board URL"]
                else []
            ),
            closed=row.notna()["Closed"],
            date_applied=(
                row["Date Applied"].to_pydatetime()
                if row.notna()["Date Applied"]
                else None
            ),
            sent_to_legal=(
                row["Sent to Legal"].to_pydatetime()
                if row.notna()["Sent to Legal"]
                else None
            ),
            role_num=role_num,
            save_posting=save_posting,
        )

    def apply(self) -> None:
        page = self.apply_prep()
        with chrome_driver(incognito=False) as webdriver:
            while page.prepare_application_form():
                time.sleep(0.1)
                self.perform_apply_action(
                    webdriver, ApplyAction.APPLICATION_PAGE
                )
            while action := self.prompt_apply_action():
                if not self.perform_apply_action(webdriver, action):
                    break

    def perform_apply_action(
        self, webdriver: Webdriver, action: ApplyAction
    ) -> bool:
        if action == ApplyAction.APPLICATION_PAGE:
            webdriver.save_pdf(self.new_saved_file("application"))
        elif action == ApplyAction.APPLICATION_SUBMITTED:
            webdriver.save_pdf(self.new_saved_file("application-submitted"))
        elif action == ApplyAction.FINISH_ROLE:
            return False
        elif action == ApplyAction.QUIT:
            sys.exit(0)
        return True

    def prompt_apply_action(self) -> ApplyAction:
        while True:
            print("")
            print(
                Fore.CYAN
                + Style.BRIGHT
                + "Available actions:"
                + Style.RESET_ALL
            )
            print("")
            indent = max(4, max(len(a.value) for a in ApplyAction))
            for aa in ApplyAction:
                print(
                    "    "
                    + Style.BRIGHT
                    + f"{aa: <{indent}} "
                    + Style.RESET_ALL
                    + aa.desc
                )
            print("")
            result = input(
                Style.BRIGHT
                + "Enter an action to continue [n]: "
                + Style.RESET_ALL
            )
            try:
                return ApplyAction((result.strip() or "n").lower())
            except ValueError:
                continue

    def apply_prep(self) -> WebdriverPage:
        self.role_path.mkdir(parents=True, exist_ok=True)
        role_resume_path = self.role_path / self.resume.name
        if not role_resume_path.exists():
            shutil.copy(self.resume, role_resume_path)
        if self.save_posting and self.role_job_board_urls:
            self.save_job_board_postings()
        with chrome_driver() as webdriver:
            page = webdriver.navigate(self.role_url)
            if self.save_posting and not self.posting_pdf_path.exists():
                time.sleep(0.5)
                webdriver.save_pdf(self.posting_pdf_path)
            self.check_posting_pdf()
            return page

    def new_saved_file(self, page_type: str, extension: str = "pdf") -> Path:
        self.saved_file_counts[page_type] += 1
        new_count = self.saved_file_counts[page_type]
        if new_count == 2:
            of = f"{page_type}-{self.date_str}.{extension}"
            nf = f"{page_type}-{new_count - 1}-{self.date_str}.{extension}"
            shutil.move(self.role_path / of, self.role_path / nf)
        fn_count = f"-{new_count}" if new_count > 1 else ""
        return (
            self.role_path
            / f"{page_type}{fn_count}-{self.date_str}.{extension}"
        )

    def save_job_board_postings(self) -> None:
        with chrome_driver() as webdriver:
            for jb_url in self.role_job_board_urls:
                page = webdriver.page(jb_url)
                ev_file = self.new_saved_file(page.page_type)
                if ev_file.exists():
                    continue
                webdriver.navigate(jb_url)
                webdriver.save_pdf(ev_file)

    @cached_property
    def role_files(self) -> list[Path]:
        if not self.role_path.exists():
            return []
        files = []
        for fp in self.role_path.iterdir():
            if fp.name == self.resume.name:
                continue
            if fp == self.posting_pdf_path:
                continue
            if fp.name.startswith("posting-"):
                continue
            files.append(fp)
        return files

    @property
    def role_path_has_activity(self) -> bool:
        return bool(self.role_files)

    @cached_property
    def checks(self) -> RoleChecks:
        rc = RoleChecks()
        for f in sorted(self.role_files):
            if f.suffix != ".pdf":
                continue
            if f.stem.startswith("email-confirmation-"):
                rc.email_confirmation = True
        return rc

    def print_urls(self) -> None:
        print("")
        if self.role_job_board_urls:
            print(
                "    Job Board URL(s): "
                + os.linesep
                + Style.BRIGHT
                + os.linesep.join(
                    [f"    {u}" for u in self.role_job_board_urls]
                )
                + Style.RESET_ALL
            )
            print("")
        print("    " + Style.BRIGHT + self.role_url + Style.RESET_ALL)
        print("")

    def print_info(
        self, compact: bool = False, prefix: str | None = None
    ) -> None:
        print(
            Fore.MAGENTA
            + Style.BRIGHT
            + ">>> "
            + Style.RESET_ALL
            + (f"{prefix} " if prefix else "")
            + Style.BRIGHT
            + self.role_title
            + Style.RESET_ALL
            + " at "
            + Style.BRIGHT
            + self.company
            + Style.RESET_ALL
            + " -> "
            + Style.BRIGHT
            + Fore.BLUE
            + str(self.role_path).removeprefix(str(config.dir) + os.sep)
            + Style.RESET_ALL
            + ((" " + self.role_url) if compact else "")
            + (
                (Style.BRIGHT + Fore.YELLOW + " (applied)" + Style.RESET_ALL)
                if self.date_applied
                else ""
            )
        )
        if not compact:
            self.print_urls()

    def text_search(self, page_num: int, text: str) -> None:
        matches = 0
        for word in config.compensation_words:
            for line in text.splitlines():
                if word.lower() in line.lower():
                    matches += 1
                    print(
                        Style.BRIGHT
                        + f"[Posting page {page_num}] "
                        + Style.RESET_ALL
                        + 'Found "'
                        + Fore.YELLOW
                        + Style.BRIGHT
                        + word
                        + Style.RESET_ALL
                        + " in [ "
                        + Style.DIM
                        + text
                        + Style.RESET_ALL
                        + " ]"
                    )
        if matches:
            self.print_urls()

    def check_posting_pdf(self) -> None:
        # Check if compensation-related words are in the PDF
        reader = PdfReader(self.posting_pdf_path)
        for i, page in enumerate(reader.pages):
            self.text_search(i + 1, page.extract_text())

    @cached_property
    def posting_pdf_path(self) -> Path:
        return self.role_path / f"posting-{self.date_str}.pdf"

    @cached_property
    def company_slug(self) -> str:
        return slugify(self.company)

    @cached_property
    def title_slug(self) -> str:
        return slugify(self.role_title)

    @cached_property
    def date_str(self) -> str:
        return (self.date_applied or datetime.now()).strftime("%Y%m%d")

    @cached_property
    def role_dir_name(self) -> str:
        return f"{self.date_str}-{self.role_num}-{self.title_slug}"

    @cached_property
    def role_path(self) -> Path:
        return config.dir / self.company_slug / self.role_dir_name
