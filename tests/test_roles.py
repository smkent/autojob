from typing import Iterator
from unittest import mock

import pytest
from responses import RequestsMock

from autojob.roles import Roles


@pytest.fixture(autouse=True)
def mock_input() -> Iterator[None]:
    with mock.patch("builtins.input", lambda *args: ""):
        yield


def test_roles_order(
    http_responses: RequestsMock, api_companies: None, api_queue: None
) -> None:
    roles = Roles()
    all_roles = [r for r in roles.companies_role_gen()]
    assert len(all_roles) == 1
    all_roles_single = all_roles[0]
    assert [r.posting.link for r in all_roles_single] == [
        "https://api.example.com/postings/10"
    ]
