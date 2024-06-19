import requests
from bs4 import BeautifulSoup
from colorama import Style  # type: ignore


def url_to_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def prompt_press_enter(prefix: str = "") -> None:
    input(Style.DIM + prefix + "Press [Enter] to continue " + Style.RESET_ALL)
    print("")
