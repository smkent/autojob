import os
from functools import cached_property
from pathlib import Path
from typing import Any, Sequence

import yaml
from slugify import slugify

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
        if ecfn := os.environ.get("CONF"):
            ecf = Path(ecfn)
            if not ecf.is_file():
                raise Exception(f"Configuration file {ecfn} not found")
            return ecf
        return CONF_FILE

    @cached_property
    def raw(self) -> dict[str, Any] | None:
        if not self.conf_file.is_file():
            return None
        with open(self.conf_file) as f:
            data = yaml.safe_load(f)
        if data:
            assert isinstance(data, dict)
            return data
        return None

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
    def dir(self) -> Path:
        return self.value_to_path("dir", HOME / "autojob").absolute()

    @cached_property
    def resume(self) -> Path:
        return self.value_to_file_path("resume")

    @cached_property
    def spreadsheet(self) -> Path:
        return self.value_to_file_path("spreadsheet", "spreadsheet.xlsx")

    @cached_property
    def spreadsheet_tab(self) -> str:
        if not self.raw or not (tab := self.raw.get("spreadsheet_tab")):
            raise Exception(
                'Configuration option "spreadsheet_tab" has no value'
            )
        assert isinstance(tab, str)
        return tab

    @cached_property
    def zip_prefix(self) -> str:
        prefix = ""
        if self.raw and (name := self.raw.get("name")):
            prefix = slugify(name) + "-"
        return f"{prefix}jobs"

    @cached_property
    def compensation_words(self) -> Sequence[str]:
        if not self.raw or not (value := self.raw.get("words")):
            return COMPENSATION_WORDS
        return sorted(list({str(word) for word in value}))


config = Config()
