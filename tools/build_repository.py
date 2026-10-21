"""Build deterministic, allowlisted Kodi packages and the public update feed."""

import argparse
import hashlib
import io
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET


def package(identifier, files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(identifier + "/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    return buffer.getvalue()


def build(root, output):
    root, output = Path(root), Path(output)
    service_files = {
        name: (root / name).read_bytes() for name in ("addon.xml", "service.py", "sync_now.py", "LICENSE", "README.md")
    }
    for path in (root / "resources").rglob("*"):
        if path.is_file() and path.suffix in (".py", ".xml", ".po", ".png", ".jpg") and "__pycache__" not in path.parts:
            service_files[path.relative_to(root).as_posix()] = path.read_bytes()
    definitions = [
        (ET.fromstring(service_files["addon.xml"]), service_files),
        (
            ET.parse(root / "repository.drahy.scprofilesync/addon.xml").getroot(),
            {
                "addon.xml": (root / "repository.drahy.scprofilesync/addon.xml").read_bytes(),
                "LICENSE": (root / "LICENSE").read_bytes(),
            },
        ),
    ]
    generated = {}
    catalog = ET.Element("addons")
    for definition, files in definitions:
        identifier, version = definition.get("id"), definition.get("version")
        catalog.append(definition)
        base = identifier + "/" + identifier + "-" + version + ".zip"
        raw = package(identifier, files)
        generated[base] = raw
        generated[base + ".sha256"] = (hashlib.sha256(raw).hexdigest() + "\n").encode()
        generated[identifier + "/addon.xml"] = files["addon.xml"]
    ET.indent(catalog, space="  ")
    generated["addons.xml"] = ET.tostring(catalog, encoding="utf-8", xml_declaration=True) + b"\n"
    generated["addons.xml.sha256"] = (hashlib.sha256(generated["addons.xml"]).hexdigest() + "\n").encode()
    for name, raw in generated.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    return generated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    result = build(project, args.output or project / "repo")
    print("Built %s public repository files" % len(result))
