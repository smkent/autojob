from __future__ import annotations

import os
from argparse import ArgumentParser, Namespace
from datetime import date, datetime, timedelta
from functools import cached_property
from pathlib import Path

from colorama import Fore, Style  # type: ignore
from dateutil.parser import parse as parse_date

from .api import CompanyPriority, api_client
from .config import ConfigSetup, config
from .roles import Roles


class AutoJobApp:
    @cached_property
    def roles(self) -> Roles:
        return Roles(
            resume=self.args.resume or config.resume,
            select_companies=set(self.args.select_companies or {}),
            skip_companies=set(self.args.skip_companies or {}),
            save_posting=self.args.save_posting,
        )

    @cached_property
    def args_tuple(self) -> tuple[Namespace, list[str]]:
        def _today() -> datetime:
            return datetime.combine(date.today(), datetime.min.time())

        def _parse_date(x: str) -> datetime | None:
            if x.lower() in {"today", "tod"}:
                return _today()
            elif x.lower() in {"yesterday", "y"}:
                return _today() - timedelta(days=1)
            elif x:
                return parse_date(x)
            return None

        def _parse_file_name(x: str) -> Path | None:
            if not x:
                return None
            if not (fp := Path(x).absolute()).is_file():
                raise Exception(f"{fp} is not a file")
            return fp

        ap = ArgumentParser(description="Job application tools")
        ap.add_argument(
            "action",
            choices=["apply", "check", "config"],
            help="Action to perform",
        )
        ap.add_argument(
            "-n",
            "--no-save-posting",
            "--skip-posting",
            dest="save_posting",
            action="store_false",
            help="Don't automatically save posting to PDF",
        )
        ap.add_argument(
            "-d",
            "--since-date",
            dest="since_date",
            metavar="date",
            type=_parse_date,
            help="Zip applications from this date or newer (default: all)",
        )
        ap.add_argument(
            "-r",
            "--resume",
            dest="resume",
            metavar="file",
            type=_parse_file_name,
            help='Resume file name (default: "resume" value in config file)',
        )
        ap.add_argument(
            "-c",
            "--company",
            dest="select_companies",
            metavar="company",
            action="append",
            type=lambda x: str(x).lower(),
            help=(
                "Name of company to include."
                " Can be specified multiple times."
                " (default: all companies included)"
            ),
        )
        ap.add_argument(
            "-s",
            "--skip-company",
            dest="skip_companies",
            metavar="company",
            action="append",
            type=lambda x: str(x).lower(),
            help=(
                "Name of company to skip."
                " Can be specified multiple times."
                " (default: no companies skipped)"
            ),
        )
        ap.add_argument(
            "-p",
            "--priority",
            dest="company_priority",
            choices=["high", "normal", "low"],
            metavar="level",
            help="Filter by company priority (choices: high, normal, low)",
        )
        ap.add_argument(
            "-w",
            "--in-wa",
            "--wa",
            dest="in_wa",
            action="store_true",
            help="Filter for roles in WA",
        )
        return ap.parse_known_args()

    @cached_property
    def args(self) -> Namespace:
        return self.args_tuple[0]

    @cached_property
    def extra_args(self) -> list[str]:
        return self.args_tuple[1]

    def __call__(self) -> None:
        if self.args.action == "config":
            ConfigSetup()()
            return
        self.print_config()
        if self.args.action == "apply":
            if self.args.company_priority is not None:
                api_client.company_priority = CompanyPriority[
                    self.args.company_priority.upper()
                ]
            if self.args.in_wa:
                api_client.in_wa = True
            self.roles.apply()
        elif self.args.action == "check":
            self.check()
        else:
            print(f"Unknown action {self.args.action}")

    def print_config(self) -> None:
        def _br(text: str | Path) -> str:
            return str(Style.BRIGHT + str(text) + Style.RESET_ALL)

        align = 16
        print(
            Fore.MAGENTA
            + _br(">>> ")
            + "Configuration ("
            + _br(config.conf_file)
            + "):"
        )
        print("")
        print("   ", f"{'PDFs dir:': >{align}}", _br(config.dir))
        print(
            "   ", f"{'Resume:': >{align}}", _br(self.roles.resume or "(none)")
        )
        print(
            "   ",
            f"{'API User:': >{align}}",
            _br(api_client.me.username),
        )
        print(
            "   ",
            f"{'Check words:': >{align}}",
            _br(", ".join(sorted(config.compensation_words))),
        )
        print("")

    def check(self) -> None:
        for role in self.roles.role_gen():
            if not role.role_path_has_activity:
                continue
            checks = role.checks
            if not checks.passed:
                role.print_info(compact=True)
                print(
                    "   ",
                    "Missing",
                    ", ".join(
                        [
                            (Style.BRIGHT + Fore.RED + n + Style.RESET_ALL)
                            for n in role.checks.failed
                        ]
                    ),
                )

    def trailing_path(self, path: Path) -> str:
        return str(path).removeprefix(str(config.dir) + os.sep)

    @cached_property
    def date_str(self) -> str:
        return datetime.now().strftime("%Y%m%d")
