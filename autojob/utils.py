import sys

import requests
from bs4 import BeautifulSoup
from colorama import Style  # type: ignore


def url_to_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def prompt_press_enter(prefix: str = "") -> None:
    try:
        input(
            Style.DIM + prefix + "Press [Enter] to continue " + Style.RESET_ALL
        )
    except KeyboardInterrupt:
        print("")
        print("")
        print("Exiting")
        sys.exit(0)
    print("")
