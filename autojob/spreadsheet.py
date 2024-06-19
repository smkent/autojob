from pandas import DataFrame, read_excel  # type: ignore

from .config import config


class Spreadsheet:
    @staticmethod
    def sheet(name: str) -> DataFrame:
        return read_excel(config.spreadsheet, name)
