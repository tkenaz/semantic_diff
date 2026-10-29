"""
Tests for the GitLab MR note: one note per merge request, found by its marker
among the token user's own notes and edited in place; every failure is a
NoteError that names the request but never the token.
"""

import http.client
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from semantic_diff import gitlab_note
from semantic_diff.gitlab_note import (
    TOKEN_VARIABLE,
    MergeRequestNote,
    MergeRequestTarget,
    NoteError,
)

MARKER = "<!-- marker -->"
TOKEN = "glpat-" + "fixture0000000000000"
ME, SOMEONE = 7, 8

ENV = {
    "CI_API_V4_URL": "https://gitlab.example.org/api/v4/",
    "CI_PROJECT_ID": "42",
    "CI_MERGE_REQUEST_IID": "5",
    TOKEN_VARIABLE: TOKEN,
}
NOTES = "https://gitlab.example.org/api/v4/projects/42/merge_requests/5/notes"


class FakeGitLab:
    """Answers /user and the notes pages; records every request"""

    def __init__(self, pages=((),), status=None):
        self.pages = [list(page) for page in pages]
        self.status = status or {}
        self.requests = []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers, json.loads(body) if body else None))
        path = url.split("?")[0]
        for (m, suffix), code in self.status.items():
            if m == method and path.endswith(suffix):
                return code, {}, b'{"message": "nope"}'
        if path.endswith("/user"):
            return 200, {}, json.dumps({"id": ME}).encode()
        if method == "GET":
            page = int(url.split("page=")[-1].split("&")[0])
            following = str(page + 1) if page < len(self.pages) else ""
            return 200, {"X-Next-Page": following}, json.dumps(self.pages[page - 1]).encode()
        return 201 if method == "POST" else 200, {}, b"{}"

    def writes(self):
        return [(m, u, p) for m, u, _, p in self.requests if m in ("POST", "PUT")]


def _note(note_id, author, body):
    return {"id": note_id, "author": {"id": author}, "body": body}


def _upsert(gitlab, env=ENV):
    return MergeRequestNote(MergeRequestTarget.from_env(env), gitlab).upsert("new body", MARKER)


class TestUpsert:
    def test_adds_a_note_when_there_is_none(self):
        gitlab = FakeGitLab()

        assert _upsert(gitlab) == "created"
        assert gitlab.writes() == [("POST", NOTES, {"body": "new body"})]

    def test_edits_its_own_marked_note_in_place(self):
        gitlab = FakeGitLab([[_note(1, ME, "unrelated"), _note(2, ME, f"{MARKER}\nold")]])

        assert _upsert(gitlab) == "updated"
        assert gitlab.writes() == [("PUT", f"{NOTES}/2", {"body": "new body"})]

    def test_a_marker_in_someone_elses_note_is_not_ours(self):
        gitlab = FakeGitLab([[_note(3, SOMEONE, f"quoting {MARKER}")]])

        assert _upsert(gitlab) == "created"
        assert [m for m, _, _ in gitlab.writes()] == ["POST"]

    def test_finds_the_note_on_a_later_page(self):
        gitlab = FakeGitLab([[_note(1, ME, "a")], [_note(9, ME, MARKER)]])

        assert _upsert(gitlab) == "updated"
        assert gitlab.writes()[0][1] == f"{NOTES}/9"

    def test_sends_the_token_as_a_header_only(self):
        gitlab = FakeGitLab()
        _upsert(gitlab)

        for _, url, headers, _ in gitlab.requests:
            assert headers["PRIVATE-TOKEN"] == TOKEN
            assert TOKEN not in url

    def test_a_path_style_project_id_is_quoted(self):
        gitlab = FakeGitLab()
        _upsert(gitlab, {**ENV, "CI_PROJECT_ID": "group/app"})

        assert gitlab.writes()[0][1].startswith(
            "https://gitlab.example.org/api/v4/projects/group%2Fapp/"
        )


class TestFailures:
    @pytest.mark.parametrize(
        "status, hint",
        [(401, TOKEN_VARIABLE), (403, "api scope"), (404, "not visible")],
    )
    def test_an_http_error_names_the_request_and_a_hint_but_not_the_token(self, status, hint):
        gitlab = FakeGitLab(status={("POST", "/notes"): status})

        with pytest.raises(NoteError) as raised:
            _upsert(gitlab)

        message = str(raised.value)
        assert f"HTTP {status}" in message and hint in message
        assert "/merge_requests/5/notes" in message
        assert TOKEN not in message

    def test_missing_variables_are_named(self):
        env = {k: v for k, v in ENV.items() if k not in ("CI_MERGE_REQUEST_IID", TOKEN_VARIABLE)}

        with pytest.raises(NoteError, match=f"CI_MERGE_REQUEST_IID, {TOKEN_VARIABLE}"):
            MergeRequestTarget.from_env(env)

    def test_an_unreachable_host_is_a_note_error(self, monkeypatch):
        class Refusing:
            def open(self, *args, **kwargs):
                raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(gitlab_note, "_opener", Refusing())
        with pytest.raises(NoteError, match="/api/v4/user: connection refused"):
            _upsert(gitlab_note.urllib_transport)

    def test_a_cut_off_response_is_a_note_error(self, monkeypatch):
        class CutOff:
            def open(self, *args, **kwargs):
                raise http.client.IncompleteRead(b"{")

        monkeypatch.setattr(gitlab_note, "_opener", CutOff())
        with pytest.raises(NoteError, match="/api/v4/user"):
            _upsert(gitlab_note.urllib_transport)

    def test_a_redirect_is_refused_and_the_token_goes_nowhere_else(self, redirecting_server):
        api, elsewhere = redirecting_server
        env = {**ENV, "CI_API_V4_URL": api}

        with pytest.raises(NoteError, match="HTTP 302"):
            _upsert(gitlab_note.urllib_transport, env)

        assert elsewhere == []


@pytest.fixture
def redirecting_server():
    """A local API that answers every request with a redirect to a second
    local server; the second one records who reached it"""
    reached = []

    class Elsewhere(BaseHTTPRequestHandler):
        def do_GET(self):
            reached.append(self.headers.get("PRIVATE-TOKEN"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"id": 1}')

        def log_message(self, *args):
            pass

    target = HTTPServer(("127.0.0.1", 0), Elsewhere)

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}{self.path}")
            self.end_headers()

        def log_message(self, *args):
            pass

    api = HTTPServer(("127.0.0.1", 0), Redirect)
    for server in (target, api):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{api.server_port}/api/v4", reached
    for server in (target, api):
        server.shutdown()
        server.server_close()
