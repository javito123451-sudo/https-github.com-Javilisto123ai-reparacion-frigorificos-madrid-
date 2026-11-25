import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fraudguard.api import create_app
from fraudguard.config import Settings
from fraudguard.llm import Extraction


class FakeProvider:
    name, model = "fake", "fake-model"

    def __init__(self, ext: Extraction | None = None, exc: Exception | None = None):
        self.ext, self.exc, self.calls = ext, exc, []

    def extract(self, *, kind, text, images, context):
        self.calls.append(dict(kind=kind, text=text, images=images, context=context))
        if self.exc:
            raise self.exc
        return self.ext or Extraction(summary="Resumen de prueba", signals=[], mitigators=[], unverifiable=[])


def png_bytes(size=(64, 48)):
    b = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def make_client(tmp_path):
    def _make(provider="default", rate=1000, fetch=None, **kw):
        s = Settings(db_path=str(tmp_path / "t.db"), rate_per_hour=rate, **kw)
        prov = FakeProvider() if provider == "default" else provider
        app = create_app(s, provider=prov, fetch=fetch)
        c = TestClient(app)
        c.provider = prov
        return c
    return _make
