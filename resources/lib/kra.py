"""Use bounded private Kra file operations; never log credentials or resolved URLs."""

import base64
import hashlib
import re
import time
from urllib.parse import urlparse

import requests

from .cancellation import SyncStopped

PREFIX = "kodi-profile-v1-"
NAME = re.compile(r"^kodi-profile-v1-([a-f0-9]{32})-(\d{12})\.json$")
TIMEOUT = (2, 2)
MAX_BYTES = 4 * 1024 * 1024


class KraError(Exception):
    pass


class Kra:
    def __init__(self, get_setting, set_setting=None, check_running=None, wait=None):
        self.get = get_setting
        self.set = set_setting or (lambda key, value: None)
        self.check_running = check_running or (lambda: None)
        self.wait = wait or time.sleep
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SC-Profile-Sync/0.1.4"
        self.token = self.get("kraska.token") or ""
        self.setting_token = self.token

    def login(self):
        result = self._request(
            "/api/user/login",
            {"data": {"username": self.get("kraska.user"), "password": self.get("kraska.pass")}},
            retry=False,
            use_token=False,
        )
        if not result.get("session_id"):
            raise KraError("Kra authentication unavailable")
        self.token = result["session_id"]
        self.set("kraska.token", self.token)
        value = self.get("kraska.pass") + "|" + self.get("kraska.user")
        self.set("kraska.chsum", hashlib.md5(value.encode("utf-8")).hexdigest())

    def _request(self, endpoint, data, retry=True, use_token=True):
        self.check_running()
        payload = dict(data)
        if use_token:
            # Stream Cinema can refresh its session after this worker starts.
            # Follow external changes without replacing a newly logged-in token
            # when a custom settings adapter has not persisted it yet.
            current = self.get("kraska.token") or ""
            if current != self.setting_token:
                self.setting_token = self.token = current
            if not self.token:
                self.login()
            payload["session_id"] = self.token
        try:
            response = self.session.post("https://api.kra.sk" + endpoint, json=payload, timeout=TIMEOUT)
            self.check_running()
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError):
            raise KraError("Kra request unavailable") from None
        if not isinstance(result, dict):
            raise KraError("Invalid Kra response")
        if result.get("error"):
            if retry and use_token and endpoint == "/api/file/list":
                self.login()
                return self._request(endpoint, data, retry=False)
            raise KraError("Kra rejected the request")
        return result

    def list(self):
        result = self._request("/api/file/list", {"data": {"parent": None, "filter": PREFIX + "*"}})
        files = result.get("data")
        if files == {}:
            files = []
        if not isinstance(files, list):
            raise KraError("Invalid Kra file listing")
        return [f for f in files if NAME.fullmatch(f.get("name", "")) and isinstance(f.get("ident"), str)]

    @staticmethod
    def _trusted_url(url):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not (parsed.hostname == "kra.sk" or parsed.hostname.endswith(".kra.sk"))
        ):
            raise KraError("Unexpected Kra transfer host")
        return url

    def download(self, file):
        result = self._request("/api/file/download", {"data": {"ident": file["ident"]}})
        url = self._trusted_url(result.get("data", {}).get("link", ""))
        try:
            response = self.session.get(url, timeout=TIMEOUT, stream=True)
            self.check_running()
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                self.check_running()
                size += len(chunk)
                if size > MAX_BYTES:
                    raise KraError("Remote profile exceeds the size limit")
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException:
            raise KraError("Kra profile download unavailable") from None

    def upload(self, name, raw):
        self.check_running()
        if not NAME.fullmatch(name) or len(raw) > MAX_BYTES:
            raise ValueError("Invalid profile upload")
        result = self._request("/api/file/create", {"data": {"name": name}, "shared": False})
        file = result.get("data", {})
        if not file.get("ident"):
            raise KraError("Kra did not create the private file")
        metadata = base64.b64encode(file["ident"].encode()).decode()
        link = self._trusted_url(file.get("link", ""))
        headers = {"Tus-Resumable": "1.0.0", "Upload-Metadata": "ident " + metadata, "Upload-Length": str(len(raw))}
        try:
            response = self.session.post(link, headers=headers, timeout=TIMEOUT, allow_redirects=False)
            self.check_running()
            if response.status_code != 201:
                raise KraError("Kra upload initialization failed")
            location = response.headers.get("Location", "")
            url = self._trusted_url("https://upload.kra.sk" + location if location.startswith("/") else location)
            headers = {
                "Tus-Resumable": "1.0.0",
                "Upload-Offset": "0",
                "Content-Type": "application/offset+octet-stream",
            }
            response = self.session.patch(url, data=raw, headers=headers, timeout=TIMEOUT)
            self.check_running()
            if response.status_code != 204:
                raise KraError("Kra did not complete the upload")
            # Newly completed private files can take a moment to become resolvable.
            for delay in (0, 0.25, 0.5, 1, 2, 3):
                self.check_running()
                if delay:
                    if self.wait(delay):
                        raise SyncStopped()
                    self.check_running()
                try:
                    if self.download(file) == raw:
                        break
                except KraError:
                    pass
            else:
                raise KraError("Kra upload readback failed")
        except KraError:
            raise
        except requests.RequestException:
            # Keep a failed object for diagnosis; never delete an unverified name.
            raise KraError("Kra profile upload unavailable") from None
        return {"name": name, "ident": file["ident"]}

    def prune(self, device, keep=2):
        from .engine import decode

        own = sorted(
            (f for f in self.list() if NAME.fullmatch(f["name"]).group(1) == device),
            key=lambda f: f["name"],
            reverse=True,
        )
        verified = 0
        for file in own:
            self.check_running()
            if verified >= keep:
                self._request("/api/file/delete", {"data": {"ident": file["ident"]}})
                continue
            try:
                data = decode(self.download(file))
                if data["device"] == device:
                    verified += 1
            except (KraError, ValueError, KeyError):
                pass
