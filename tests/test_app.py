import io
import json
import os
from unittest import mock

import pytest


# ---------- helpers ----------

@pytest.mark.parametrize("name,expected", [
    ("doc.pdf", True), ("notes.TXT", True), ("a.b.pdf", True),
    ("image.png", False), ("noext", False), ("pdf", False), (".txt", True),
])
def test_allowed_file(app_module, name, expected):
    assert app_module.allowed_file(name) is expected


def test_folders_created_on_import(app_module, tmp_path):
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "conversations").is_dir()


def test_conversation_roundtrip_preserves_unicode(app_module):
    conv = [{"sender": "user", "message": "Ciao, è tutto ok?"},
            {"sender": "bot", "message": "Sì"}]
    app_module.save_conversation("abc", conv)
    assert app_module.load_conversation("abc") == conv
    path = os.path.join(app_module.CONVERSATION_FOLDER, "session_abc.json")
    with open(path, encoding="utf-8") as f:
        assert "è" in f.read()  # ensure_ascii=False


def test_load_missing_conversation_returns_empty(app_module):
    assert app_module.load_conversation("does-not-exist") == []


def test_list_conversations(app_module):
    app_module.save_conversation("s1", [])
    app_module.save_conversation("s2", [])
    open(os.path.join(app_module.CONVERSATION_FOLDER, "ignore.txt"), "w").close()
    result = app_module.list_conversations()
    assert sorted(c["session_id"] for c in result) == ["s1", "s2"]
    for c in result:
        assert len(c["timestamp"]) == len("2024-01-01 00:00:00")


def test_load_uploaded_documents_reads_txt_and_pdf(app_module):
    up = app_module.app.config["UPLOAD_FOLDER"]
    with open(os.path.join(up, "a.txt"), "w", encoding="utf-8") as f:
        f.write("hello text")
    open(os.path.join(up, "b.pdf"), "wb").close()
    open(os.path.join(up, "c.png"), "wb").close()
    with mock.patch.object(app_module, "extract_text_from_pdf", return_value="pdf body"):
        docs = app_module.load_uploaded_documents()
    assert docs == {"a.txt": "hello text", "b.pdf": "pdf body"}


def test_extract_text_from_pdf_joins_pages(app_module):
    pages = [mock.Mock(extract_text=mock.Mock(return_value="p1")),
             mock.Mock(extract_text=mock.Mock(return_value="p2"))]
    pdf = mock.MagicMock()
    pdf.__enter__.return_value.pages = pages
    app_module.pdfplumber.open.return_value = pdf
    assert app_module.extract_text_from_pdf("x.pdf") == "p1\np2\n"


# ---------- retrieval ----------

def test_retriever_ranks_most_relevant_first(app_module):
    docs = {
        "cats.txt": "cats purr and cats like milk",
        "cars.txt": "cars have engines and wheels",
        "space.txt": "rockets fly to the moon",
    }
    r = app_module.DocumentRetriever(docs)
    top = r.retrieve("engines wheels", top_k=2)
    assert len(top) == 2
    assert top[0] == ("cars.txt", docs["cars.txt"])
    assert r.retrieve("moon rockets", top_k=1)[0][0] == "space.txt"


# ---------- Ollama calls (network mocked) ----------

def _resp(status, payload=None):
    return mock.Mock(status_code=status, json=mock.Mock(return_value=payload))


def test_talk_to_ollama_success(app_module):
    with mock.patch.object(app_module.requests, "post",
                           return_value=_resp(200, {"response": "hi"})) as post:
        assert app_module.talk_to_ollama("ciao", model="m") == "hi"
    assert post.call_args.args[0] == app_module.OLLAMA_API_URL
    assert post.call_args.kwargs["json"] == {"model": "m", "prompt": "ciao", "stream": False}


def test_talk_to_ollama_error(app_module):
    with mock.patch.object(app_module.requests, "post", return_value=_resp(500)):
        assert app_module.talk_to_ollama("x").startswith("Sorry")


def test_talk_to_ollama_with_rag_builds_context(app_module):
    retriever = mock.Mock()
    retriever.retrieve.return_value = [("a", "CTX1"), ("b", "CTX2")]
    with mock.patch.object(app_module.requests, "post",
                           return_value=_resp(200, {"response": "ok"})) as post:
        assert app_module.talk_to_ollama_with_rag("Q?", retriever) == "ok"
    prompt = post.call_args.kwargs["json"]["prompt"]
    assert prompt == "Context:\nCTX1\nCTX2\n\nPrompt:\nQ?"


# ---------- routes ----------

def test_upload_rejects_missing_and_bad_files(client):
    assert client.post("/upload", data={}).status_code == 400
    r = client.post("/upload", data={"file": (io.BytesIO(b""), "")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/upload", data={"file": (io.BytesIO(b"x"), "evil.exe")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert r.get_json()["message"] == "File type not allowed"


def test_upload_saves_sanitized_filename(client, app_module):
    r = client.post("/upload", data={"file": (io.BytesIO(b"data"), "../my notes.txt")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert os.listdir(app_module.app.config["UPLOAD_FOLDER"]) == ["my_notes.txt"]


def test_new_conversation_redirects_to_chat(client):
    r = client.get("/new_conversation")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/chat")
    with client.session_transaction() as s:
        assert len(s["session_id"]) == 36


def test_send_message_without_rag_persists(client, app_module):
    with client.session_transaction() as s:
        s["session_id"] = "sess"
    with mock.patch.object(app_module, "talk_to_ollama", return_value="pong"):
        r = client.post("/send_message", json={"message": "ping"})
    assert r.get_json() == {"response": "pong"}
    assert app_module.load_conversation("sess") == [
        {"sender": "user", "message": "ping"},
        {"sender": "bot", "message": "pong"},
    ]


def test_send_message_rag_without_documents(client, app_module):
    with client.session_transaction() as s:
        s["session_id"] = "sess"
    with mock.patch.object(app_module, "talk_to_ollama_with_rag") as rag:
        r = client.post("/send_message", json={"message": "q", "use_rag": True})
    rag.assert_not_called()
    assert "caricare un documento" in r.get_json()["response"]


def test_send_message_rag_with_documents(client, app_module):
    with open(os.path.join(app_module.app.config["UPLOAD_FOLDER"], "d.txt"), "w") as f:
        f.write("python flask testing")
    with client.session_transaction() as s:
        s["session_id"] = "sess"
    with mock.patch.object(app_module, "talk_to_ollama_with_rag", return_value="rag!") as rag:
        r = client.post("/send_message", json={"message": "flask", "use_rag": True})
    assert r.get_json()["response"] == "rag!"
    assert isinstance(rag.call_args.args[1], app_module.DocumentRetriever)


def test_conversations_list_endpoint(client, app_module):
    app_module.save_conversation("zz", [])
    data = client.get("/conversations_list").get_json()
    assert [c["session_id"] for c in data] == ["zz"]


def test_index_and_chat_render(client, app_module):
    app_module.save_conversation("old", [{"sender": "user", "message": "hello-there"}])
    assert client.get("/").status_code == 200
    r = client.get("/conversation/old")
    assert r.status_code == 200
    assert b"hello-there" in r.data


def test_commands_json_is_valid():
    path = os.path.join(os.path.dirname(__file__), "..", "commands.json")
    with open(path, encoding="utf-8") as f:
        cmds = json.load(f)
    assert cmds
    for val in cmds.values():
        assert {"command", "description"} <= set(val)
        assert val["description"].strip()
