# Job application tools

[![Build](https://img.shields.io/github/checks-status/smkent/autojob/main?label=build)][gh-actions]
[![codecov](https://codecov.io/gh/smkent/autojob/branch/main/graph/badge.svg)][codecov]
[![GitHub stars](https://img.shields.io/github/stars/smkent/autojob?style=social)][repo]

**Warning:** This is experimental, use at your own risk

## Installation notes

On Windows, ensure
[Windows Long Path support is enabled][windows-long-path-support].

## Development

### [Poetry][poetry] installation

Via [`pipx`][pipx]:

```console
pip install pipx
pipx install poetry
pipx inject poetry poetry-pre-commit-plugin
```

Via `pip`:

```console
pip install poetry
poetry self add poetry-pre-commit-plugin
```

### Development tasks

* Setup: `poetry install`
* Run static checks: `poetry run poe lint` or
  `poetry run pre-commit run --all-files`
* Run static checks and tests: `poetry run poe test`

---

Created from [smkent/cookie-python][cookie-python] using
[cookiecutter][cookiecutter]

[codecov]: https://codecov.io/gh/smkent/autojob
[cookie-python]: https://github.com/smkent/cookie-python
[cookiecutter]: https://github.com/cookiecutter/cookiecutter
[gh-actions]: https://github.com/smkent/autojob/actions?query=branch%3Amain
[pipx]: https://pypa.github.io/pipx/
[poetry]: https://python-poetry.org/docs/#installation
[repo]: https://github.com/smkent/autojob
[windows-long-path-support]: https://pip.pypa.io/warnings/enable-long-paths
