import json
import os
from tempfile import NamedTemporaryFile
from typing import Iterable, Iterator
from unittest import mock

import pytest
import responses
import yaml

from autojob.config import Config

from .data import (
    make_companies_response,
    make_queue_response,
    make_session_response,
)

TEST_CONF = {
    "api": "https://api.example.com/",
    "api_key": "deadbeef",
    "dir": "~/",
}


@pytest.fixture(autouse=True)
def http_responses() -> Iterable[responses.RequestsMock]:
    with responses.RequestsMock() as resp_mock:
        yield resp_mock


@pytest.fixture
def api_me_call(
    http_responses: responses.RequestsMock,
) -> None:
    http_responses.add(
        method=responses.GET,
        url="https://api.example.com/me",
        body=json.dumps(make_session_response()),
    )


@pytest.fixture
def api_companies(
    http_responses: responses.RequestsMock,
) -> None:
    http_responses.add(
        method=responses.GET,
        url="https://api.example.com/companies?limit=1000",
        body=json.dumps(make_companies_response()),
    )


@pytest.fixture
def api_queue(
    http_responses: responses.RequestsMock,
) -> None:
    http_responses.add(
        method=responses.GET,
        url="https://api.example.com/queue?limit=1000",
        body=json.dumps(make_queue_response()),
    )


@pytest.fixture(autouse=True)
def conf(http_responses: responses.RequestsMock) -> Iterator[Config]:
    with NamedTemporaryFile(suffix=".conf.yaml") as tf, mock.patch.dict(
        os.environ, {"CONF": tf.name}
    ):
        with open(tf.name, "w") as f:
            f.write(yaml.dump(TEST_CONF))
        yield Config()
