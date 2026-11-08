"""Test setup: import app/app.py in an isolated temp dir with pdfplumber stubbed."""
import importlib
import os
import sys
import types
from unittest import mock

import pytest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    # Stub pdfplumber so tests don't need it (only used for PDF parsing).
    stub = types.ModuleType("pdfplumber")
    stub.open = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "pdfplumber", stub)
    # app.py creates 'uploads' and 'conversations' relative to cwd at import time.
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(APP_DIR)
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    module.app.config["TESTING"] = True
    module.app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    monkeypatch.setattr(module, "CONVERSATION_FOLDER", str(tmp_path / "conversations"))
    yield module
    sys.modules.pop("app", None)


@pytest.fixture
def client(app_module):
    return app_module.app.test_client()
