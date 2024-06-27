from __future__ import annotations

import base64
import os
import re
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar, Iterator, Literal, Sequence

import selenium.webdriver.support.expected_conditions as ec
from colorama import Fore, Style  # type: ignore
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.remote.webdriver import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.wait import WebDriverWait

from .api import api_client
from .config import config
from .utils import prompt_press_enter


@dataclass
class Webdriver:
    drivers: list[webdriver.Chrome] = field(default_factory=list)
    existing_chrome_first_run: bool = field(init=False, default=True)

    @contextmanager
    def __call__(self, incognito: bool = False) -> Iterator[Webdriver]:
        method = (
            self._chrome_driver_incognito
            if incognito
            else self._chrome_driver_existing_session
        )
        url = None
        if self.drivers:
            url = self.driver.current_url
        with method() as driver:
            self.drivers.insert(0, driver)
            if url:
                self.navigate(url)
            yield self
            self.drivers.pop(0)

    @property
    def driver(self) -> webdriver.Chrome:
        if not self.drivers:
            raise Exception("No drivers active")
        return self.drivers[0]

    def wait(self, timeout: float = 3) -> WebDriverWait:
        return WebDriverWait(self.driver, timeout)

    def navigate(self, url: str) -> WebdriverPage:
        self.driver.switch_to.window(self.driver.current_window_handle)
        self.driver.implicitly_wait(3)
        self.driver.get(url)
        time.sleep(0.25)
        page = self.page(url)
        page.process_page()
        return page

    def page(self, url: str) -> WebdriverPage:
        return WebdriverPage.from_url(self, url)

    def el(self, locator: str, by: str = By.XPATH) -> WebElement:
        return self.driver.find_element(by, locator)

    def el_all(self, locator: str, by: str = By.XPATH) -> Sequence[WebElement]:
        return self.driver.find_elements(by, locator)

    def el_wait(
        self,
        locator: WebElement | str,
        by: str = By.XPATH,
        timeout: float = 3,
        condition: Callable[
            [Any],
            Callable[[ec.WebDriverOrWebElement], WebElement | Literal[False]],
        ] = ec.presence_of_element_located,
    ) -> WebElement:
        target = locator if isinstance(locator, WebElement) else (by, locator)
        el = self.wait(timeout=timeout).until(condition(target))
        if el is False:
            raise NoSuchElementException(f"({target}) condition is False")
        return el

    def el_clickable(
        self, locator: WebElement | str, by: str = By.XPATH
    ) -> WebElement:
        el = self.el_wait(locator, by, condition=ec.element_to_be_clickable)
        self.scroll(el, block="center")
        return el

    def scroll(
        self,
        element: WebElement,
        block: Literal["center", "start", "end", "nearest"] = "start",
    ) -> None:
        self.driver.execute_script(
            "arguments[0].scrollIntoView("
            "{block: '" + block + "', behavior: 'instant'}"
            ");",
            element,
        )

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

    @contextmanager
    def _chrome_driver_incognito(self) -> Iterator[webdriver.Chrome]:
        options = webdriver.ChromeOptions()
        driver = webdriver.Chrome(options=options)
        yield driver
        driver.quit()

    @contextmanager
    def _chrome_driver_existing_session(self) -> Iterator[webdriver.Chrome]:
        if self.existing_chrome_first_run:
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
            self.existing_chrome_first_run = False
        options = webdriver.ChromeOptions()
        options.add_experimental_option("debuggerAddress", "localhost:9014")
        driver = webdriver.Chrome(options=options)
        yield driver
        driver.quit()


@dataclass
class WebdriverPage:
    webdriver: Webdriver
    url: str
    page_type: ClassVar[str] = ""
    subclasses: ClassVar[list[type[WebdriverPage]]] = []
    patterns: ClassVar[Sequence[str]] = []

    def __init_subclass__(cls) -> None:
        cls.subclasses.append(cls)

    def process_page(self) -> None:
        pass

    def prepare_application_form(self) -> bool:
        return False

    def page_file_name(self, count: int = 0) -> str:
        fn_count = f"-{count}" if count > 1 else ""
        return f"{self.page_type}{fn_count}"

    @classmethod
    def from_url(cls, webdriver: Webdriver, url: str) -> WebdriverPage:
        def _class_for_url(url: str) -> type[WebdriverPage]:
            for subclass in cls.subclasses:
                if not subclass.patterns:
                    continue
                for pattern in subclass.patterns:
                    if re.search(pattern, url):
                        return subclass
            return WebdriverPage

        return _class_for_url(url)(webdriver, url)


class WebdriverPosting(WebdriverPage):
    page_type = "posting"


class LeverPosting(WebdriverPage):
    patterns = [r":\/\/jobs\.(eu\.)?lever\.co\/"]

    def prepare_application_form(self) -> bool:
        self.webdriver.navigate(self.url.removesuffix("/") + "/apply")
        return False


class LinkedInPosting(WebdriverPosting):
    page_type = "posting-linkedin"
    patterns = [r":\/\/(www\.)?linkedin\.com\/"]

    def process_page(self) -> None:
        self.webdriver.wait().until(
            ec.element_to_be_clickable(
                (By.XPATH, "//button [contains(., 'See more')]")
            )
        ).click()

    def prepare_application_form(self) -> bool:
        with suppress(TimeoutException):
            self.webdriver.wait(timeout=1).until(
                ec.element_to_be_clickable(
                    (By.XPATH, "//main//button[contains(., 'Easy Apply')]")
                )
            ).click()
        return False


class GreenhousePosting(WebdriverPage):
    patterns = [
        r":\/\/boards\.(eu\.)?greenhouse\.io\/",
        r"\?gh_jid=[0-9]+$",
    ]

    def _prefill_fields(self) -> None:
        for el_name, value in [
            ("first_name", api_client.me.first_name),
            ("last_name", api_client.me.last_name),
            ("email", api_client.me.email),
            ("phone", api_client.me.phone),
        ]:
            if not value:
                continue
            with suppress(NoSuchElementException):
                el = self.webdriver.el(
                    "//input[@type='text']"
                    f"[@name='job_application[{el_name}]']"
                )
                if el.get_attribute("aria-required") == "true":
                    el.send_keys(value)

    def prepare_application_form(self) -> bool:
        with suppress(TimeoutException):
            form = self.webdriver.wait().until(
                ec.presence_of_element_located(
                    (
                        By.XPATH,
                        (
                            "//form[@id='application_form']"
                            "[contains(@action, '://boards.greenhouse.io')]"
                        ),
                    ),
                )
            )
            self._prefill_fields()
            self.webdriver.scroll(form)
            form.click()
        return False


class ShopifyPosting(WebdriverPosting):
    patterns = [r":\/\/(www\.)?shopify\.com\/careers\/"]

    def prepare_application_form(self) -> bool:
        application_h2 = self.webdriver.el_wait("//h2[text()='Application']")
        if not application_h2.is_displayed():
            self._prepare_screening_questions()
            return True
        button = self.webdriver.el_clickable(
            "//section/button[contains(., 'Submit')]"
        )
        button.click()
        self._prefill_fields()
        self.webdriver.scroll(application_h2)
        application_h2.click()
        return False

    def _prepare_screening_questions(self) -> None:
        button = self.webdriver.el_clickable(
            "//button [contains(., 'Apply Now')]"
        )
        button.click()
        for checkbox in self.webdriver.el_all(
            "//input[@type='checkbox'][contains(@name, 'screening')]",
        ):
            self.webdriver.el_clickable(checkbox)
            checkbox.click()
            time.sleep(0.1)

    def _prefill_fields(self) -> None:
        for text in [
            "Do you have the right to work",
            "agree with our candidate NDA",
            "applicant privacy notice",
        ]:
            try:
                el = self.webdriver.el_clickable(
                    f'//div[contains(text(), "{text}")]'
                    "/preceding-sibling::input[@type='checkbox']"
                )
                el.click()
                time.sleep(0.1)
            except NoSuchElementException:
                pass
        for el_name, value in [
            ("_systemfield_name", api_client.me.full_name),
            ("_systemfield_email", api_client.me.email),
        ]:
            if not value:
                continue
            with suppress(NoSuchElementException):
                self.webdriver.el_clickable(
                    f"//input[@name='{el_name}']"
                ).send_keys(value)
