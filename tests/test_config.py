import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator
from unittest import mock

import pytest
import yaml

from autojob.config import Config

TEST_CONF = {
    "api": "https://api.example.com/",
    "api_key": "deadbeef",
    "dir": "~/",
}


@pytest.fixture
def conf() -> Iterator[Config]:
    with NamedTemporaryFile(suffix=".conf.yaml") as tf, mock.patch.dict(
        os.environ, {"CONF": tf.name}
    ):
        with open(tf.name, "w") as f:
            f.write(yaml.dump(TEST_CONF))
        yield Config()


def test_config(conf: Config) -> None:
    assert conf.dir == Path("~/").expanduser()
    assert conf.resume is None
    assert conf.api_url == "https://api.example.com/"
    assert conf.api_key == "deadbeef"
