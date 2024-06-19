from __future__ import annotations

import base64
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterator

from colorama import Fore, Style  # type: ignore
from selenium import webdriver
from selenium.webdriver.remote.webdriver import By

from .config import config
from .utils import prompt_press_enter


@dataclass
class Webdriver:
    driver: webdriver.Chrome

    def navigate(self, url: str) -> WebdriverPage:
        self.driver.switch_to.window(self.driver.current_window_handle)
        self.driver.implicitly_wait(5)
        self.driver.get(url)
        time.sleep(0.25)
        page = self.page(url)
        page.process_page()
        return page

    def page(self, url: str) -> WebdriverPage:
        return WebdriverPage.from_url(self, url)

    def save_pdf(self, dest: Path) -> None:
        pdf = self.driver.execute_cdp_cmd(
            "Page.printToPDF",
            {
                "printBackground": True,
                "displayHeaderFooter": True,
                "scale": 1.0,
            },
        )
        with open(dest, "wb") as f:
            f.write(base64.b64decode(pdf["data"]))
        print(
            Fore.GREEN
            + "Saved page to PDF: "
            + str(dest).removeprefix(str(config.dir) + os.sep)
            + Style.RESET_ALL
        )
        print("")


@dataclass
class ChromeDriverManager:
    first_run: bool = True

    @contextmanager
    def __call__(self) -> Iterator[Webdriver]:
        with self.chrome_driver_existing_session() as driver:
            yield Webdriver(driver)

    @contextmanager
    def chrome_driver_existing_session(self) -> Iterator[webdriver.Chrome]:
        if self.first_run:
            self._startup_prompt()
            self.first_run = False
        options = webdriver.ChromeOptions()
        options.add_experimental_option("debuggerAddress", "localhost:9014")
        driver = webdriver.Chrome(options=options)
        yield driver
        driver.quit()

    def _startup_prompt(self) -> None:
        print("")
        print(
            Fore.CYAN
            + Style.BRIGHT
            + "Action required: "
            + Style.RESET_ALL
            + "Ensure Chrome is running with the following options:"
            + os.linesep * 2
            + Style.BRIGHT
            + (
                "google-chrome"
                " -remote-debugging-port=9014"
                " --profile-directory=Default"
            )
            + Style.RESET_ALL
        )
        print("")
        prompt_press_enter()


@dataclass
class WebdriverPage:
    webdriver: Webdriver
    url: str
    page_type: ClassVar[str] = ""
    subclasses: ClassVar[list[type[WebdriverPage]]] = []
    pattern: ClassVar[str] = ""

    def __init_subclass__(cls) -> None:
        cls.subclasses.append(cls)

    def process_page(self) -> None:
        pass

    def page_file_name(self, count: int = 0) -> str:
        fn_count = f"-{count}" if count > 1 else ""
        return f"{self.page_type}{fn_count}"

    @classmethod
    def from_url(cls, webdriver: Webdriver, url: str) -> WebdriverPage:
        def _class_for_url(url: str) -> type[WebdriverPage]:
            for subclass in cls.subclasses:
                if subclass.pattern and re.search(subclass.pattern, url):
                    return subclass
            return WebdriverPage

        return _class_for_url(url)(webdriver, url)


class WebdriverPosting(WebdriverPage):
    page_type = "posting"


class LinkedInPosting(WebdriverPosting):
    page_type = "posting-linkedin"
    pattern = r":\/\/(www\.)?linkedin\.com\/"

    def process_page(self) -> None:
        see_more_button = self.webdriver.driver.find_element(
            By.XPATH, "//button [contains(., 'See more')]"
        )
        see_more_button.click()
