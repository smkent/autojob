from pathlib import Path

from autojob.config import Config


def test_config(conf: Config) -> None:
    assert conf.dir == Path("~/").expanduser()
    assert conf.resume is None
    assert conf.api_url == "https://api.example.com/"
    assert conf.api_key == "deadbeef"
