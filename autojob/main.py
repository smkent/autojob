from __future__ import annotations

import os
import sys
import tempfile
from argparse import ArgumentParser, Namespace
from datetime import date, datetime, timedelta
from functools import cached_property
from pathlib import Path
from zipfile import ZipFile

from colorama import Fore, Style  # type: ignore
from dateutil.parser import parse as parse_date

from .config import ConfigSetup, config
from .roles import Roles
from .utils import prompt_press_enter


class AutoJobApp:
    @cached_property
    def roles(self) -> Roles:
        return Roles(
            self.args.resume or config.resume,
            set(self.args.select_companies or {}),
            set(self.args.skip_companies or {}),
            self.args.check_duplicate_urls,
            self.args.save_posting,
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
            choices=["apply", "check", "zip", "unzip", "config"],
            help="Action to perform",
        )
        ap.add_argument(
            "-2",
            "--check-duplicate-urls",
            dest="check_duplicate_urls",
            action="store_true",
            help="Check for duplicate role URLs in spreadsheet tab",
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
                "Name of company in spreadsheet to include."
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
                "Name of company in spreadsheet to skip."
                " Can be specified multiple times."
                " (default: no companies skipped)"
            ),
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
            self.roles.apply()
        elif self.args.action == "check":
            self.check()
        elif self.args.action == "zip":
            self.zip()
        elif self.args.action == "unzip":
            self.unzip()
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
        print("   ", f"{'Resume:': >{align}}", _br(self.roles.resume))
        print("   ", f"{'Spreadsheet:': >{align}}", _br(config.spreadsheet))
        print(
            "   ",
            f"{'Spreadsheet tab:': >{align}}",
            _br(config.spreadsheet_tab),
        )
        print(
            "   ",
            f"{'Zip file prefix:': >{align}}",
            _br(config.zip_prefix),
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

    def zip(self) -> None:
        def _print_action(action: str, color: str = Fore.GREEN) -> None:
            print(
                Style.BRIGHT
                + color
                + ">>> "
                + Style.RESET_ALL
                + action
                + " "
                + Style.BRIGHT
                + self.trailing_path(zip_path)
                + Style.RESET_ALL
            )

        zip_path = config.dir / f"{config.zip_prefix}-{self.date_str}.zip"
        if zip_path.exists():
            _print_action("Error: Zip file already exists:", color=Fore.RED)
            sys.exit(1)
        _print_action("Creating", color=Fore.MAGENTA)
        role_count = 0
        with ZipFile(str(zip_path), mode="w") as z:
            z.write(
                config.spreadsheet,
                self.trailing_path(config.spreadsheet),
            )
            for role in self.roles.role_gen(
                lambda r: bool(r.notna()["Date Applied"]) is True
            ):
                if role.sent_to_legal:
                    continue
                if (
                    self.args.since_date
                    and role.date_applied < self.args.since_date
                ):
                    continue
                role_count += 1
                role.print_info(compact=True)
                for path in role.role_path.glob("**/*"):
                    z.write(str(path), self.trailing_path(path))
        _print_action(
            "Saved "
            + Style.BRIGHT
            + str(role_count)
            + Style.RESET_ALL
            + " cases to"
        )

    def unzip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="autojob-unzip.") as td:
            print("Unzipping files to " + Style.BRIGHT + td + Style.RESET_ALL)
            print("")
            for zip_file in sorted([i for i in config.dir.glob("*.zip")]):
                print("Unzipping", zip_file)
                with ZipFile(zip_file) as z:
                    z.extractall(td)
            print("")
            print("Unzipped files to " + Style.BRIGHT + td + Style.RESET_ALL)
            print("")
            prompt_press_enter()

    def trailing_path(self, path: Path) -> str:
        return str(path).removeprefix(str(config.dir) + os.sep)

    @cached_property
    def date_str(self) -> str:
        return datetime.now().strftime("%Y%m%d")
