import os
import sys
from contextlib import suppress
from functools import cached_property
from pathlib import Path
from textwrap import indent
from typing import Any, Sequence

import yaml
from colorama import Style  # type: ignore

HOME = Path.home()
CONF_FILE = HOME / ".autojob.yaml"
COMPENSATION_WORDS = ("$", "USD", "salary", "compensation")


class ConfigValueMissing(ValueError):
    pass


class ConfigValueFileMissing(ValueError):
    pass


class Config:
    @cached_property
    def conf_file(self) -> Path:
        if fn := os.environ.get("CONF"):
            return Path(fn)
        return CONF_FILE

    @cached_property
    def raw(self) -> dict[str, Any]:
        if not self.conf_file.is_file():
            return {}
        with open(self.conf_file) as f:
            data = yaml.safe_load(f)
        if data:
            assert isinstance(data, dict)
            return data
        return {}

    def value_to_path(
        self, key: str, default: Path | str | None = None
    ) -> Path:
        if not self.raw or not (value := self.raw.get(key)):
            if default:
                if isinstance(default, str):
                    default = Path(default)
                return default
            raise ConfigValueMissing(f'No configuration value for "{key}"')
        return Path(value).expanduser()

    def value_to_file_path(
        self, key: str, default: Path | str | None = None
    ) -> Path:
        path = self.value_to_path(key, default)
        if not path.is_absolute():
            path = self.dir / path
        if not path.is_file():
            raise ConfigValueFileMissing(
                f'File {path} for "{key}" configuration value does not exist'
            )
        return path

    @cached_property
    def api_url(self) -> str:
        if not self.raw:
            return ""
        return self.raw.get("api") or ""

    @cached_property
    def api_key(self) -> str:
        if not self.raw:
            return ""
        return self.raw.get("api_key") or ""

    @cached_property
    def dir(self) -> Path:
        return self.value_to_path("dir", HOME / "autojob").absolute()

    @cached_property
    def resume(self) -> Path | None:
        with suppress(ConfigValueMissing):
            return self.value_to_file_path("resume")
        return None

    @cached_property
    def spreadsheet(self) -> Path | None:
        with suppress(ConfigValueFileMissing):
            return self.value_to_file_path("spreadsheet", "spreadsheet.xlsx")
        return None

    @cached_property
    def spreadsheet_tab(self) -> str:
        if not self.raw or not (tab := self.raw.get("spreadsheet_tab")):
            raise Exception(
                'Configuration option "spreadsheet_tab" has no value'
            )
        assert isinstance(tab, str)
        return tab

    @cached_property
    def compensation_words(self) -> Sequence[str]:
        if not self.raw or not (value := self.raw.get("words")):
            return COMPENSATION_WORDS
        return sorted(list({str(word) for word in value}))


config = Config()


class ConfigSetup:
    config_keys = ["dir", "resume", "api", "api_key"]

    def __call__(self) -> None:
        new_conf: dict[str, str] = {}
        for key in self.config_keys:
            existing_value = config.raw.get(key) or ""
            # One-off preprocessing
            if key == "spreadsheet_tab" and not existing_value:
                existing_value = (
                    config.raw.get("name") or new_conf.get("name") or ""
                ).rsplit(" ", -1)[0]
            existing_str = (
                (" [" + Style.BRIGHT + existing_value + Style.RESET_ALL + "]")
                if existing_value
                else ""
            )
            sys.stdout.write(Style.RESET_ALL)
            new_value = (
                input(f"{key}{existing_str}: " + Style.BRIGHT)
                or existing_value
            )

            new_conf[key] = new_value
        new_yaml = yaml.dump(new_conf)
        with open(config.conf_file, "w") as f:
            f.write(new_yaml)
        print("")
        print(
            "Wrote config file "
            + Style.BRIGHT
            + str(config.conf_file)
            + Style.RESET_ALL
            + ":"
        )
        print("")
        print(indent(new_yaml, prefix="    "))
