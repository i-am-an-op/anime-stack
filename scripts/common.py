"""Small, host-side helpers. No Docker socket is mounted into a container."""

import fcntl
import http.cookiejar
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIB = 1024**3
SERVICES = ("autobangumi", "qbittorrent")


def read_json(path):
    return json.loads(Path(path).read_text())


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(value if isinstance(value, str) else json.dumps(value, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def dotenv(path):
    result = {}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                if "=" not in line:
                    raise ValueError("Configuration must use KEY=value lines")
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip()
                if key in result:
                    raise ValueError("Duplicate configuration key: " + key)
                if any(c in value for c in "\"'`$\\\r\n#"):
                    raise ValueError("Use literal, unquoted configuration values: " + key)
                result[key] = value
    return result


def settings():
    return {**dotenv(ROOT / ".env.example"), **dotenv(ROOT / ".env")}


def resolve_path(value):
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def data_dir():
    return resolve_path(settings().get("DATA_DIR", "./runtime"))


def media_dir():
    return resolve_path(settings().get("MEDIA_DIR", "./runtime/media"))


def policy():
    from preflight import validate_policy

    return validate_policy(read_json(data_dir() / "policy.json"))


def versions():
    return read_json(ROOT / "versions.json")


def run(argv, *, check=True, input=None, timeout=180, env=None):
    result = subprocess.run(
        argv, input=input, text=True, capture_output=True, timeout=timeout, cwd=ROOT, env=env
    )
    if check and result.returncode:
        # Do not echo command arguments or application output: either can contain secrets.
        raise RuntimeError(f"{Path(argv[0]).name} failed (exit {result.returncode})")
    return result


def compose(*args, **kwargs):
    config = settings()
    env = {**os.environ, **config}
    return run(
        [
            "docker",
            "compose",
            "--project-name",
            config["COMPOSE_PROJECT_NAME"],
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(ROOT / ".env"),
            "-f",
            str(ROOT / "compose.yaml"),
            *args,
        ],
        env=env,
        **kwargs,
    )


def container(service):
    cid = compose("ps", "--all", "--quiet", service).stdout.strip()
    if not cid:
        return None
    return json.loads(run(["docker", "inspect", cid]).stdout)[0]


def running_services():
    return [s for s in SERVICES if (c := container(s)) and c["State"]["Running"]]


@contextmanager
def operation_lock(blocking=True):
    (data_dir() / "ops").mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(data_dir() / "ops/operation.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class API:
    def __init__(self, service, credentials=None):
        info = container(service)
        if not info or not info["State"]["Running"]:
            raise RuntimeError(f"{service} is stopped")
        config = settings()
        port = config["QB_WEB_PORT"] if service == "qbittorrent" else config["AB_WEB_PORT"]
        self.base = f"http://127.0.0.1:{port}"
        self.service = service
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        self.credentials = (
            credentials or read_json(data_dir() / "secrets/credentials.json")[service]
        )

    def request(self, path, *, method="GET", form=None, data=None, raw=False):
        headers = {"Referer": self.base + "/", "Origin": self.base}
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path, data=body, headers=headers, method=method
        )
        with self.opener.open(request, timeout=10) as response:
            content = response.read().decode()
        if raw or not content:
            return content
        return json.loads(content)

    def login(self):
        if self.service == "qbittorrent":
            result = self.request(
                "/api/v2/auth/login", method="POST", form=self.credentials, raw=True
            )
            if result.strip() not in ("Ok.", ""):
                raise RuntimeError("qBittorrent authentication failed")
            # Current qBittorrent may return an empty successful response. Prove
            # authentication with a protected endpoint instead of trusting text.
            self.preferences()
        else:
            self.request("/api/v1/auth/login", method="POST", form=self.credentials)
        return self

    def logout(self):
        path = "/api/v2/auth/logout" if self.service == "qbittorrent" else "/api/v1/auth/logout"
        self.request(path, method="POST", raw=True)

    def torrents(self):
        return self.request("/api/v2/torrents/info")

    def stop_torrents(self):
        self.request("/api/v2/torrents/stop", method="POST", form={"hashes": "all"}, raw=True)

    def preferences(self, values=None):
        if values is None:
            return self.request("/api/v2/app/preferences")
        self.request(
            "/api/v2/app/setPreferences", method="POST", form={"json": json.dumps(values)}, raw=True
        )
