from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from lxml import etree


def validate_url(url: str) -> tuple[bool, str]:
    if not url.startswith(("http://", "https://")):
        return False, "URL musí začínat http:// nebo https://"
    try:
        resp = requests.head(url, allow_redirects=True, timeout=10)
        resp.raise_for_status()
        return True, "URL je dostupná."
    except requests.HTTPError as e:
        return False, f"Server vrátil chybu: {e.response.status_code}"
    except requests.Timeout:
        return False, "Požadavek vypršel — server neodpovídá."
    except Exception as e:
        return False, f"URL není dostupná: {e}"


def download_xml(url: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.fromstring(response.content, parser=parser)

    parsed = urlparse(url)
    stem = Path(parsed.path).name or "feed"
    if not stem.endswith(".xml"):
        stem = f"{stem}.xml" if stem else "feed.xml"

    out_path = output_dir / f"{uuid.uuid4().hex}_{stem}"
    with open(out_path, "wb") as f:
        f.write(etree.tostring(tree, pretty_print=True, xml_declaration=True, encoding="UTF-8"))

    return out_path


def stream_xml_from_url(url: str):
    response = requests.get(url, stream=True)
    response.raise_for_status()
    for event, element in etree.iterparse(response.raw, events=("end",)):
        yield element
        element.clear()
