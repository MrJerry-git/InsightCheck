import base64
import io
import json
import zipfile
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.schemas.smart_import import ImportRequest
from app.services.smart_import import extract, prepare

client = TestClient(app)


def upload(name, raw):
    return {"file": {"name": name, "content": base64.b64encode(raw).decode()}}


def mock_model(monkeypatch, result):
    response = MagicMock()
    response.json.return_value = {"message": {"content": json.dumps(result)}}
    mock = MagicMock()
    mock.__enter__.return_value.post.return_value = response
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: mock)
    return mock


def test_text_evidence_and_unknowns(monkeypatch):
    mock_model(monkeypatch, {"sex": "female", "known_cvd": False,
                            "visits": [{"sbp": 120, "smoking": False}],
                            "evidence": [{"path": "sex", "quote": "女"},
                                         {"path": "visits.0.sbp", "quote": "120 mmHg"},
                                         {"path": "visits.0.smoking", "quote": "不吸烟"}]})
    result = extract(ImportRequest(text="女，收缩压120 mmHg"))
    assert result["draft"]["sex"] == "female"
    assert result["draft"]["known_cvd"] is None
    assert result["draft"]["visits"][0]["smoking"] is None
    assert result["draft"]["visits"][0]["sbp"] == 120
    assert result["requires_confirmation"] is True
    assert "visits.0.date" in result["missing"]


@pytest.mark.parametrize("body", [{}, upload("x.exe", b"x"),
                                    {"file": {"name": "x.txt", "content": "!"}},
                                    upload("x.txt", b"x" * 16001)])
def test_reject_bad_or_empty_documents(body):
    response = client.post("/api/v1/prevention/smart-import/extract", json=body)
    assert response.status_code == 422


def test_utf8_and_docx():
    text = "收缩压 120 mmHg"
    assert prepare(ImportRequest(**upload("x.txt", text.encode())))[0].strip() == text
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                   'wordprocessingml/2006/main"><w:p><w:r><w:t>120</w:t></w:r></w:p></w:document>')
    assert "120" in prepare(ImportRequest(**upload("x.docx", stream.getvalue())))[0]


def test_images():
    stream = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(stream, format="PNG")
    text, images = prepare(ImportRequest(**upload("x.png", stream.getvalue())))
    assert text == ""
    assert len(images) == 1
    with Image.open(io.BytesIO(base64.b64decode(images[0]))) as image:
        assert image.size == (200, 100)


def test_pdf_and_page_limit():
    import pypdfium2 as pdfium
    with pdfium.PdfDocument.new() as pdf:
        page = pdf.new_page(100, 100)
        page.close()
        stream = io.BytesIO()
        pdf.save(stream)
        assert len(prepare(ImportRequest(**upload("x.pdf", stream.getvalue())))[1]) == 1
        for _ in range(5):
            page = pdf.new_page(100, 100)
            page.close()
        stream = io.BytesIO()
        pdf.save(stream)
        with pytest.raises(ValueError, match="1–5"):
            prepare(ImportRequest(**upload("x.pdf", stream.getvalue())))


def test_model_failure_not_fake_success(monkeypatch):
    mock = MagicMock()
    mock.__enter__.return_value.post.side_effect = httpx.ConnectError("private information")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: mock)
    response = client.post("/api/v1/prevention/smart-import/extract", json={"text": "体检"})
    assert response.status_code == 503
    assert "private information" not in response.text


def test_invalid_model_output(monkeypatch):
    mock_model(monkeypatch, {"visits": [{"sbp": True}]})
    response = client.post("/api/v1/prevention/smart-import/extract", json={"text": "test"})
    assert response.status_code == 422


def test_confirm_requires_complete_input_and_explicit_confirmation():
    assert client.post("/api/v1/prevention/smart-import/confirm",
                       json={"confirmed": False, "intake": {}}).status_code == 422
    assert client.post("/api/v1/prevention/smart-import/confirm",
                       json={"confirmed": True, "intake": {}}).status_code == 422


def test_confirm_to_real_assessment():
    from test_prevention import case
    response = client.post("/api/v1/prevention/smart-import/confirm",
                           json={"confirmed": True, "intake": case()})
    assert response.status_code == 200
    intake = response.json()["intake"]
    assert "用户核对" in intake["source_note"]
    assessment = client.post("/api/v1/prevention/assess", json=intake)
    assert assessment.status_code == 200
    assert assessment.json()["risk"] is not None


def test_import_endpoint_is_local_only():
    from pydantic import ValidationError

    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(import_model_url="https://external.example.com")


def test_lock_returns_busy():
    from app.api.routes.smart_import import lock
    lock.acquire()
    try:
        response = client.post("/api/v1/prevention/smart-import/extract", json={"text": "test"})
        assert response.status_code == 429
    finally:
        lock.release()


def test_timeout(monkeypatch):
    mock = MagicMock()
    mock.__enter__.return_value.post.side_effect = httpx.ReadTimeout("timeout")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: mock)
    response = client.post("/api/v1/prevention/smart-import/extract", json={"text": "test"})
    assert response.status_code == 504
