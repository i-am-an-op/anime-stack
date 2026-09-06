# Contributing

Open an issue for a bug or a substantial behavior change, then submit a focused pull request. Small fixes may go directly to a pull request. Keep examples generic and use reserved documentation domains such as `example.com`.

## Development

Python runtime code uses the standard library and supports Python 3.12+. Development tooling is pinned separately:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check scripts tests
.venv/bin/ruff format --check scripts tests
python3 -m unittest discover -s tests -v
```

Run integration checks only in a disposable Docker project whose name contains `test`, with no subscriptions or torrents. They stop services, create a disk hold, encrypt backups and restore them into a temporary directory:

```sh
ANIME_STACK_TESTING=1 python3 tests/integration.py
```

The workflow shows the full disposable setup. Never run lifecycle tests against a deployment containing real downloads. Do not submit logs or runtime state as test fixtures. Use synthetic fixtures for credential, path-traversal and state-transition tests.

## Review and releases

- Explain the concrete problem, resulting behavior and relevant validation in the pull request.
- Keep Docker image pins immutable. Changing a tag/digest also requires checking `versions.json`, authentication, schema migration, networking and backup/restore behavior.
- Pin Actions by full commit SHA. Dependabot proposes action and Python-tool updates; container upgrades receive manual compatibility review.
- Use conventional commit subjects, for example `fix: preserve a disk hold during backup`.
- Update the changelog for user-visible changes. Releases use semantic versions; breaking operational changes require migration notes.
- Scan files and Git history with Gitleaks before publication. Do not suppress a credential finding just to make CI pass.

By contributing, you agree to license your original contribution under this repository's MIT license. Respect upstream licenses and use primary sources when documenting application behavior.
