"""
One note on a GitLab merge request, kept up to date: the first run adds it,
later runs find it by a hidden marker and edit it in place.

Only notes written by the token's own user count. Anyone can paste the
marker into a comment; editing theirs would fail, or worse, hijack it.
Posting is advisory: a failure is a warning, never a failed job.
"""

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

TOKEN_VARIABLE = "SEMANTIC_DIFF_GITLAB_TOKEN"
TIMEOUT_SECONDS = 30
PAGE_SIZE = 100


class NoteError(Exception):
    """The note could not be posted; the message never carries the token"""


@dataclass(frozen=True)
class MergeRequestTarget:
    api_url: str
    project_id: str
    mr_iid: str
    token: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "MergeRequestTarget":
        names = ("CI_API_V4_URL", "CI_PROJECT_ID", "CI_MERGE_REQUEST_IID", TOKEN_VARIABLE)
        missing = [name for name in names if not env.get(name)]
        if missing:
            raise NoteError(f"not set: {', '.join(missing)}")
        return cls(
            api_url=env["CI_API_V4_URL"].rstrip("/"),
            project_id=env["CI_PROJECT_ID"],
            mr_iid=env["CI_MERGE_REQUEST_IID"],
            token=env[TOKEN_VARIABLE],
        )


# (method, url, headers, body) -> (status, headers, body)
Transport = Callable[[str, str, Mapping[str, str], Optional[bytes]], tuple]


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """urllib would resend PRIVATE-TOKEN to wherever a redirect points, and turn
    a POST into a GET: a redirect is an error here, not a detour."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirects)


def urllib_transport(method, url, headers, body):
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with _opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        reason = getattr(e, "reason", e)
        raise NoteError(f"{method} {_path_only(url)}: {reason}") from None


class MergeRequestNote:
    def __init__(self, target: MergeRequestTarget, transport: Transport = urllib_transport):
        self._target = target
        self._transport = transport

    def upsert(self, body: str, marker: str, *, create: bool = True) -> str:
        """Edit our marked note if there is one, else add it (unless create is False);
        returns "created", "updated" or "absent"."""
        me = self._call("GET", "/user")["id"]
        notes = self._notes_path()
        for note in self._pages(notes):
            if note.get("author", {}).get("id") == me and marker in note.get("body", ""):
                self._call("PUT", f"{notes}/{note['id']}", {"body": body})
                return "updated"
        if not create:
            return "absent"
        self._call("POST", notes, {"body": body})
        return "created"

    def _notes_path(self) -> str:
        project = urllib.parse.quote(self._target.project_id, safe="")
        return f"/projects/{project}/merge_requests/{self._target.mr_iid}/notes"

    def _pages(self, path: str):
        page = "1"
        while page:
            query = urllib.parse.urlencode({"per_page": PAGE_SIZE, "page": page, "sort": "asc"})
            notes, headers = self._call("GET", f"{path}?{query}", with_headers=True)
            yield from notes
            page = {k.lower(): v for k, v in headers.items()}.get("x-next-page", "")

    def _call(self, method: str, path: str, payload=None, with_headers: bool = False):
        url = self._target.api_url + path
        headers = {"PRIVATE-TOKEN": self._target.token, "Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        status, response_headers, raw = self._transport(method, url, headers, body)
        if not 200 <= status < 300:
            raise NoteError(f"{method} {_path_only(url)}: HTTP {status}{_hint(status)}")
        data = json.loads(raw or b"null")
        return (data, response_headers) if with_headers else data


def _hint(status: int) -> str:
    return {
        401: f" (check {TOKEN_VARIABLE})",
        403: " (the token needs the api scope and at least Reporter on the project)",
        404: " (project or merge request not visible to the token)",
    }.get(status, "")


def _path_only(url: str) -> str:
    return urllib.parse.urlsplit(url).path
