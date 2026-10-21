import hashlib
import io
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from tools.build_repository import build


def test_feed_packages_are_deterministic_and_contain_only_public_addon_files(tmp_path):
    root = Path(__file__).parents[1]
    first = build(root, tmp_path / "first")
    assert first == build(root, tmp_path / "second")
    assert first["addons.xml.sha256"].decode().strip() == hashlib.sha256(first["addons.xml"]).hexdigest()
    definitions = ET.fromstring(first["addons.xml"])
    assert {node.get("id") for node in definitions} == {"service.sc.profilesync", "repository.drahy.scprofilesync"}
    # Repository dir versions refer to xbmc.addon API versions, not Kodi's 21.x release.
    repository = definitions.find("addon[@id='repository.drahy.scprofilesync']")
    assert repository.find("extension/dir").get("minversion") is None
    for definition in definitions:
        identifier, version = definition.get("id"), definition.get("version")
        path = identifier + "/" + identifier + "-" + version + ".zip"
        assert first[path + ".sha256"].decode().strip() == hashlib.sha256(first[path]).hexdigest()
        with zipfile.ZipFile(io.BytesIO(first[path])) as archive:
            assert archive.testzip() is None
            assert ET.fromstring(archive.read(identifier + "/addon.xml")).get("version") == version
            for name in archive.namelist():
                assert name.startswith(identifier + "/")
                assert not any(
                    part in name.split("/") for part in ("userdata", "private", ".git", "tests", "__pycache__", "repo")
                )
                assert not name.endswith(("device.json", "state.json", "storage.db", ".pyc"))
