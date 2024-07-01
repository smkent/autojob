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
from typing import Sequence

from colorama import Fore, Style  # type: ignore
from pypdf import PdfReader
from slugify import slugify

from .api import Application, Posting, api_client
from .chrome_driver import Webdriver, WebdriverPage
from .config import config


class InvalidSavedFile(ValueError):
    pass


class ApplyAction(StrEnum):
    desc: str

    def __new__(cls, value: str, desc: str = "") -> ApplyAction:
        member = str.__new__(cls, value)
        member._value_ = value
        member.desc = desc
        return member

    @staticmethod
    def all(
        include_incognito: bool = False,
    ) -> Sequence[ApplyAction]:
        actions = [
            ApplyAction.APPLICATION_PAGE,
            ApplyAction.RESAVE_APPLICATION_PAGE,
            ApplyAction.APPLICATION_SUBMITTED_ONLY,
            ApplyAction.APPLICATION_SUBMITTED,
            ApplyAction.POSTING,
        ]
        if include_incognito:
            actions.append(ApplyAction.INCOGNITO)
        actions += [
            ApplyAction.FINISH_ROLE,
            ApplyAction.CLOSE_ROLE,
            ApplyAction.SKIP,
            ApplyAction.QUIT,
        ]
        return actions

    APPLICATION_PAGE = "a", "Save application PDF"
    RESAVE_APPLICATION_PAGE = "ra", "Re-save last application page PDF"
    APPLICATION_SUBMITTED_ONLY = (
        "as",
        "Save application submitted PDF",
    )
    APPLICATION_SUBMITTED = (
        "s",
        "Save application submitted PDF and continue to next role",
    )
    INCOGNITO = "i", "Re-open posting in incognito mode"
    POSTING = "p", "Re-save posting PDF from current page"
    FINISH_ROLE = "n", "Next role"
    CLOSE_ROLE = (
        "close",
        "Mark this role as closed for everyone and remove its files",
    )
    SKIP = "skip", "Skip role and remove its files"
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
    posting: Posting
    resume: Path | None
    save_posting: bool = False
    saved_file_counts: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    webdriver: Webdriver | None = None

    def get_webdriver(self) -> Webdriver:
        if not self.webdriver:
            raise Exception("No webdriver provided")
        return self.webdriver

    def apply(self) -> None:
        try:
            page = self.apply_prep()
            self.apply_form(page)
        except Exception as e:
            print(f"Quitting due to an error: {e}")
            print("")
            self.apply_cancel()
            raise

    def apply_form(self, page: WebdriverPage, incognito: bool = False) -> None:
        while page.prepare_application_form():
            time.sleep(0.1)
            self.perform_apply_action(ApplyAction.APPLICATION_PAGE)
        actions = ApplyAction.all(include_incognito=not incognito)
        try:
            while action := self.prompt_apply_action(actions):
                if action == ApplyAction.INCOGNITO and not incognito:
                    with self.get_webdriver()(incognito=True):
                        self.apply_form(page, incognito=True)
                    return
                if not self.perform_apply_action(action):
                    break
        except KeyboardInterrupt:
            print("")
            print("")
            self.apply_quit()

    def apply_quit(self) -> None:
        self.apply_cancel()
        print("Exiting")
        sys.exit(0)

    def save_application(self) -> None:
        application = api_client.save_application(
            Application(posting=self.posting)
        )
        print(
            "Saved application: "
            + Style.BRIGHT
            + application.link
            + Style.RESET_ALL
        )
        print("")

    def perform_apply_action(self, action: ApplyAction) -> bool:
        if action == ApplyAction.APPLICATION_PAGE:
            self.get_webdriver().save_pdf(self.new_saved_file("application"))
        elif action == ApplyAction.RESAVE_APPLICATION_PAGE:
            try:
                self.get_webdriver().save_pdf(
                    self.new_saved_file("application", increment=False)
                )
            except InvalidSavedFile as e:
                print(e)
                print("")
        elif action == ApplyAction.APPLICATION_SUBMITTED_ONLY:
            self.get_webdriver().save_pdf(
                self.new_saved_file("application-submitted")
            )
        elif action == ApplyAction.APPLICATION_SUBMITTED:
            self.get_webdriver().save_pdf(
                self.new_saved_file("application-submitted")
            )
            self.save_application()
            return False
        elif action == ApplyAction.POSTING:
            self.get_webdriver().save_pdf(self.posting_pdf_path)
        elif action == ApplyAction.SKIP:
            self.apply_cancel()
            return False
        elif action == ApplyAction.CLOSE_ROLE:
            self.apply_close_role()
            self.apply_cancel()
            return False
        elif action == ApplyAction.FINISH_ROLE:
            self.save_application()
            return False
        elif action == ApplyAction.QUIT:
            self.apply_quit()
        return True

    def prompt_apply_action(
        self, actions: Sequence[ApplyAction]
    ) -> ApplyAction:
        while True:
            print(
                Fore.CYAN
                + Style.BRIGHT
                + "Available actions:"
                + Style.RESET_ALL
            )
            print("")
            indent = max(4, max(len(a.value) for a in actions))
            for aa in actions:
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
                + "Enter an action to continue: "
                + Style.RESET_ALL
            )
            print("")
            if not result.strip():
                continue
            try:
                action = ApplyAction((result.strip() or "n").lower())
                if action in actions:
                    return action
            except ValueError:
                continue

    def apply_prep(self) -> WebdriverPage:
        self.role_path.mkdir(parents=True, exist_ok=True)
        if self.resume:
            role_resume_path = self.role_path / self.resume.name
            if not role_resume_path.exists():
                shutil.copy(self.resume, role_resume_path)
        if self.save_posting and self.posting.job_board_urls:
            self.save_job_board_postings()
        page = self.get_webdriver().navigate(self.posting.url)
        if self.save_posting and not self.posting_pdf_path.exists():
            time.sleep(0.5)
            self.get_webdriver().save_pdf(self.posting_pdf_path)
        if self.posting_pdf_path.is_file():
            self.check_posting_pdf()
        return page

    def apply_close_role(self) -> None:
        note = input("(Optional) Role closed note: ").strip()
        print("")
        self.posting.closed = datetime.now()
        self.posting.closed_note = note or ""
        api_client.save_posting(self.posting)
        print(
            "Marked role as closed: "
            + Style.BRIGHT
            + self.posting.link
            + Style.RESET_ALL
        )
        print("")

    def apply_cancel(self) -> None:
        if self.role_path.is_dir():
            print(f"Delete {self.role_path} and all its contents?")
            print("")
            for fn in sorted(self.role_path.rglob("*")):
                print(
                    "    " + str(fn).removeprefix(str(self.role_path) + os.sep)
                )
            print("")
            result = input("[y/N] ").strip().lower()
            print("")
            if result != "y":
                return
            shutil.rmtree(self.role_path)
            print(f"Deleted {self.role_path}")
            company_dir = config.dir / self.company_slug
            if len([f for f in company_dir.rglob("*")]) == 0:
                company_dir.rmdir()
                print(f"Deleted empty {company_dir}")
            print("")

    def new_saved_file(
        self, page_type: str, extension: str = "pdf", increment: bool = True
    ) -> Path:
        if increment:
            self.saved_file_counts[page_type] += 1
        new_count = self.saved_file_counts[page_type]
        if new_count == 0:
            raise InvalidSavedFile(
                f"There are no existing saved {page_type} files for this role"
            )
        if increment and new_count == 2:
            of = f"{page_type}-{self.date_str}.{extension}"
            nf = f"{page_type}-{new_count - 1}-{self.date_str}.{extension}"
            shutil.move(self.role_path / of, self.role_path / nf)
        fn_count = f"-{new_count}" if new_count > 1 else ""
        return (
            self.role_path
            / f"{page_type}{fn_count}-{self.date_str}.{extension}"
        )

    def save_job_board_postings(self) -> None:
        for jb_url in self.posting.job_board_urls:
            page = self.get_webdriver().page(jb_url)
            ev_file = self.new_saved_file(page.page_type)
            if ev_file.exists():
                continue
            self.get_webdriver().navigate(jb_url)
            self.get_webdriver().save_pdf(ev_file)

    @cached_property
    def role_files(self) -> list[Path]:
        if not self.role_path.exists():
            return []
        files = []
        for fp in self.role_path.iterdir():
            if self.resume and fp.name == self.resume.name:
                continue
            if fp == self.posting_pdf_path:
                continue
            if fp.name.startswith("posting-"):
                continue
            if fp.name.startswith(".nfs"):
                continue
            files.append(fp)
        return files

    @property
    def role_path_has_activity(self) -> bool:
        return bool(self.role_files)

    @cached_property
    def similar_role_paths(self) -> Sequence[Path]:
        assert isinstance(self.posting, Posting)
        return [
            fn
            for fn in (config.dir / self.company_slug).glob(
                f"{self.posting.pk}-*"
            )
            if fn != self.role_path
        ]

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
        if self.posting.job_board_urls:
            print(
                "    Job Board URL(s): "
                + os.linesep
                + Style.BRIGHT
                + os.linesep.join(
                    [f"    {u}" for u in self.posting.job_board_urls]
                )
                + Style.RESET_ALL
            )
            print("")
        print("    " + Style.BRIGHT + self.posting.url + Style.RESET_ALL)
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
            + self.posting.title
            + Style.RESET_ALL
            + " at "
            + Style.BRIGHT
            + self.posting.company.name
            + Style.RESET_ALL
            + " -> "
            + Style.BRIGHT
            + Fore.BLUE
            + str(self.role_path).removeprefix(str(config.dir) + os.sep)
            + Style.RESET_ALL
            + ((" " + self.posting.url) if compact else "")
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
        return slugify(self.posting.company.name)

    @cached_property
    def title_slug(self) -> str:
        return slugify(self.posting.title)

    @cached_property
    def date_str(self) -> str:
        return datetime.now().strftime("%Y%m%d")

    @cached_property
    def role_dir_name(self) -> str:
        return f"{self.posting.pk}-{self.date_str}-{self.title_slug}"

    @cached_property
    def role_path(self) -> Path:
        return config.dir / self.company_slug / self.role_dir_name
