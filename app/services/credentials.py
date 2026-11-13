"""Credential URL ingestion (Open Graph meta) and platform certificate sync."""

from __future__ import annotations

import json
import logging
import re
import socket
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from ..config import UPLOAD_DIR
from ..db import connect, now

logger = logging.getLogger("openclass.credentials")

ALLOWED_PLATFORMS = {"coursera", "udemy", "github"}
ALLOWED_UPLOAD_SUFFIX = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
META_LIMIT_BYTES = 512_000
FETCH_TIMEOUT = 12

VERIFY_HOST_HINTS = (
    "coursera.org",
    "credly.com",
    "udemy.com",
    "accredible.com",
    "linkedin.com",
    "badgr.io",
    "edx.org",
)


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "meta":
            attr = {k.lower(): (v or "") for k, v in attrs}
            key = (attr.get("property") or attr.get("name") or "").lower()
            content = attr.get("content", "").strip()
            if key and content:
                self.meta[key] = content
        elif tag.lower() == "title" and not self.title:
            self.title = ""

    def handle_data(self, data: str) -> None:
        if self.lasttag == "title" and data.strip():
            self.title = data.strip()


def _hostname_blocked(host: str) -> bool:
    h = (host or "").lower().strip(".")
    if not h or h in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True
    if h.endswith(".local") or h.endswith(".internal"):
        return True
    try:
        for info in socket.getaddrinfo(h, None):
            addr = info[4][0]
            if addr.startswith("127.") or addr.startswith("10.") or addr.startswith("192.168."):
                return True
            if addr.startswith("169.254."):
                return True
    except OSError:
        return True
    return False


def _safe_fetch_html(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("URL must start with https:// or http://")
    if parsed.scheme == "http":
        url = url.replace("http://", "https://", 1)
        parsed = urlparse(url)
    if _hostname_blocked(parsed.hostname or ""):
        raise ValueError("URL host is not allowed")

    headers = {
        "User-Agent": "OpenclassCredentialBot/1.0 (+https://openclass.local)",
        "Accept": "text/html,application/xhtml+xml",
    }
    resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT, stream=True, allow_redirects=True)
    resp.raise_for_status()
    final_host = urlparse(resp.url).hostname or ""
    if _hostname_blocked(final_host):
        raise ValueError("Redirect target is not allowed")

    chunks: list[bytes] = []
    size = 0
    for chunk in resp.iter_content(chunk_size=8192):
        if not chunk:
            continue
        size += len(chunk)
        if size > META_LIMIT_BYTES:
            break
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        return raw.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        return raw.decode("utf-8", errors="replace")


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "coursera.org" in host:
        return "coursera"
    if "udemy.com" in host:
        return "udemy"
    if "credly.com" in host or "badgr" in host:
        return "credly"
    if "github.com" in host:
        return "github"
    if "edx.org" in host:
        return "edx"
    if "linkedin.com" in host:
        return "linkedin"
    return "web"


def extract_open_graph(url: str, html: Optional[str] = None) -> dict[str, Any]:
    body = html if html is not None else _safe_fetch_html(url)
    parser = _MetaParser()
    parser.feed(body)

    def pick(*keys: str) -> str:
        for key in keys:
            val = parser.meta.get(key.lower())
            if val:
                return val.strip()
        return ""

    title = pick("og:title", "twitter:title") or parser.title
    description = pick("og:description", "twitter:description", "description")
    image = pick("og:image", "twitter:image")
    site_name = pick("og:site_name")

    if not title:
        m = re.search(r"<title[^>]*>([^<]+)</title>", body, re.I)
        if m:
            title = m.group(1).strip()

    platform = detect_platform(url)
    issuer = site_name or platform.title()
    if platform == "coursera":
        issuer = "Coursera"
    elif platform == "udemy":
        issuer = "Udemy"
    elif platform == "credly":
        issuer = "Credly"

    return {
        "title": title or "Verified credential",
        "description": description,
        "image_url": image,
        "issuer": issuer,
        "platform": platform,
        "verify_url": url.split("#")[0].strip(),
    }


def _find_verify_links(html: str, base_url: str) -> list[str]:
    patterns = [
        r"https?://(?:www\.)?coursera\.org/verify/[A-Za-z0-9_-]+",
        r"https?://(?:www\.)?udemy\.com/certificate/[A-Za-z0-9/_-]+",
        r"https?://(?:www\.)?credly\.com/badges/[A-Za-z0-9_-]+",
    ]
    found: list[str] = []
    for pat in patterns:
        for match in re.findall(pat, html, flags=re.I):
            if match not in found:
                found.append(match.split("?")[0])
    return found[:24]


def resolve_student_id(current_user: dict) -> str:
    return str(
        current_user.get("roster_id")
        or current_user.get("roll_no")
        or current_user.get("student_id")
        or current_user.get("id")
    )


def upsert_credential(student_id: str, card: dict, *, source: str) -> dict:
    stamp = now()
    verify_url = card["verify_url"]
    with connect() as db:
        db.execute(
            """INSERT INTO student_credentials (
                   student_id, source, platform, title, issuer, description,
                   image_url, verify_url, issued_at, meta_json, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(student_id, verify_url) DO UPDATE SET
                   source = excluded.source,
                   platform = excluded.platform,
                   title = excluded.title,
                   issuer = excluded.issuer,
                   description = excluded.description,
                   image_url = excluded.image_url,
                   issued_at = excluded.issued_at,
                   meta_json = excluded.meta_json,
                   updated_at = excluded.updated_at""",
            (
                student_id,
                source,
                card.get("platform"),
                card.get("title") or "Credential",
                card.get("issuer"),
                card.get("description"),
                card.get("image_url"),
                verify_url,
                card.get("issued_at"),
                json.dumps(card.get("meta") or {}),
                stamp,
                stamp,
            ),
        )
        row = db.execute(
            "SELECT * FROM student_credentials WHERE student_id = ? AND verify_url = ?",
            (student_id, verify_url),
        ).fetchone()
    return credential_row_to_dict(dict(row) if row else {})


def credential_row_to_dict(row: dict) -> dict:
    if not row:
        return {}
    meta = {}
    try:
        meta = json.loads(row.get("meta_json") or "{}")
    except json.JSONDecodeError:
        meta = {}
    return {
        "id": row.get("id"),
        "student_id": row.get("student_id"),
        "source": row.get("source"),
        "platform": row.get("platform"),
        "title": row.get("title"),
        "issuer": row.get("issuer"),
        "description": row.get("description"),
        "image_url": row.get("image_url"),
        "verify_url": row.get("verify_url"),
        "issued_at": row.get("issued_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "meta": meta,
        "file_path": row.get("file_path"),
        "original_filename": row.get("original_filename"),
        "has_file": bool(row.get("file_path")),
    }


def list_credentials(student_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM student_credentials WHERE student_id = ? ORDER BY updated_at DESC",
            (student_id,),
        ).fetchall()
    out = []
    for r in rows:
        card = credential_row_to_dict(dict(r))
        if card.get("has_file") and card.get("id"):
            card["download_url"] = f"/api/student/credentials/{card['id']}/download"
        out.append(card)
    return out


def delete_credential(student_id: str, cred_id: int) -> bool:
    file_path: Optional[str] = None
    with connect() as db:
        row = db.execute(
            "SELECT file_path FROM student_credentials WHERE id = ? AND student_id = ?",
            (cred_id, student_id),
        ).fetchone()
        if row:
            file_path = row["file_path"]
        cur = db.execute(
            "DELETE FROM student_credentials WHERE id = ? AND student_id = ?",
            (cred_id, student_id),
        )
    if file_path:
        try:
            path = Path(file_path)
            if path.is_file():
                path.unlink()
        except OSError:
            logger.warning("Could not delete credential file %s", file_path)
    return cur.rowcount > 0


def get_credential_for_student(student_id: str, cred_id: int) -> Optional[dict]:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM student_credentials WHERE id = ? AND student_id = ?",
            (cred_id, student_id),
        ).fetchone()
    return credential_row_to_dict(dict(row)) if row else None


def save_local_credential(
    student_id: str,
    *,
    disk_path: Path,
    original_filename: str,
    title: str,
    issuer: Optional[str] = None,
    description: Optional[str] = None,
    verify_url: Optional[str] = None,
) -> dict:
    token = uuid.uuid4().hex
    verify_key = (verify_url or "").strip() or f"local://{student_id}/{token}"
    suffix = Path(original_filename).suffix.lower()
    platform = "local"
    stamp = now()
    meta = {"original_filename": original_filename, "upload_token": token}
    with connect() as db:
        db.execute(
            """INSERT INTO student_credentials (
                   student_id, source, platform, title, issuer, description,
                   image_url, verify_url, issued_at, meta_json, file_path, original_filename,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
            (
                student_id,
                "local_upload",
                platform,
                title or original_filename,
                issuer or "Inter-college / offline",
                description,
                image_url,
                verify_key,
                json.dumps(meta),
                str(disk_path),
                original_filename,
                stamp,
                stamp,
            ),
        )
        row = db.execute(
            "SELECT * FROM student_credentials WHERE student_id = ? AND verify_url = ?",
            (student_id, verify_key),
        ).fetchone()
    card = credential_row_to_dict(dict(row) if row else {})
    if card.get("id"):
        card["download_url"] = f"/api/student/credentials/{card['id']}/download"
    return card


def list_integrations(student_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT id, student_id, platform, token_type, account_label, scopes, connected_at, last_sync_at FROM student_integration_connections WHERE student_id = ?",
            (student_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        extra = {}
        try:
            extra = json.loads(d.get("scopes") or "{}")
        except json.JSONDecodeError:
            extra = {}
        out.append(
            {
                "platform": d.get("platform"),
                "connected": True,
                "account_label": d.get("account_label"),
                "connected_at": d.get("connected_at"),
                "last_sync_at": d.get("last_sync_at"),
                "profile_url": extra.get("profile_url"),
            }
        )
    return out


def save_integration(
    student_id: str,
    platform: str,
    access_token: str,
    *,
    account_label: Optional[str] = None,
    profile_url: Optional[str] = None,
) -> dict:
    platform = platform.lower().strip()
    if platform not in ALLOWED_PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    token = (access_token or "").strip()
    if len(token) < 8:
        raise ValueError("Access token is too short")

    meta = {}
    if profile_url:
        meta["profile_url"] = profile_url.strip()
    stamp = now()
    with connect() as db:
        db.execute(
            """INSERT INTO student_integration_connections (
                   student_id, platform, access_token, token_type, account_label, scopes, connected_at, last_sync_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
               ON CONFLICT(student_id, platform) DO UPDATE SET
                   access_token = excluded.access_token,
                   account_label = excluded.account_label,
                   scopes = excluded.scopes,
                   connected_at = excluded.connected_at""",
            (
                student_id,
                platform,
                token,
                "bearer",
                account_label or platform.title(),
                json.dumps(meta),
                stamp,
            ),
        )
    return {"platform": platform, "connected": True, "connected_at": stamp}


def disconnect_integration(student_id: str, platform: str) -> bool:
    with connect() as db:
        cur = db.execute(
            "DELETE FROM student_integration_connections WHERE student_id = ? AND platform = ?",
            (student_id, platform.lower()),
        )
    return cur.rowcount > 0


def _get_connection(student_id: str, platform: str) -> Optional[dict]:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM student_integration_connections WHERE student_id = ? AND platform = ?",
            (student_id, platform.lower()),
        ).fetchone()
    return dict(row) if row else None


def _github_sync(student_id: str, token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    user_resp = requests.get("https://api.github.com/user", headers=headers, timeout=FETCH_TIMEOUT)
    if user_resp.status_code == 401:
        raise ValueError("Invalid GitHub token")
    user_resp.raise_for_status()
    user = user_resp.json()
    login = user.get("login") or "github-user"
    profile_url = user.get("html_url") or f"https://github.com/{login}"

    saved: list[dict] = []
    saved.append(
        upsert_credential(
            student_id,
            {
                "title": f"GitHub · {user.get('name') or login}",
                "description": user.get("bio") or "Connected GitHub profile",
                "image_url": user.get("avatar_url"),
                "issuer": "GitHub",
                "platform": "github",
                "verify_url": profile_url,
                "meta": {"login": login, "type": "profile"},
            },
            source="github",
        )
    )

    repos_resp = requests.get(
        "https://api.github.com/user/repos",
        headers=headers,
        params={"per_page": 50, "sort": "updated"},
        timeout=FETCH_TIMEOUT,
    )
    if repos_resp.ok:
        for repo in repos_resp.json():
            name = (repo.get("name") or "").lower()
            topics = [t.lower() for t in (repo.get("topics") or [])]
            desc = (repo.get("description") or "").lower()
            if not any(k in name for k in ("cert", "badge", "credential", "certificate")) and "certificate" not in topics:
                if "certificate" not in desc and "coursera" not in desc and "udemy" not in desc:
                    continue
            saved.append(
                upsert_credential(
                    student_id,
                    {
                        "title": repo.get("full_name") or name,
                        "description": repo.get("description") or "GitHub learning artifact",
                        "image_url": None,
                        "issuer": "GitHub",
                        "platform": "github",
                        "verify_url": repo.get("html_url") or profile_url,
                        "meta": {"login": login, "type": "repository"},
                    },
                    source="github",
                )
            )
    return saved


def _profile_link_sync(student_id: str, platform: str, profile_url: str, source: str) -> list[dict]:
    html = _safe_fetch_html(profile_url)
    links = _find_verify_links(html, profile_url)
    saved: list[dict] = []
    for link in links:
        try:
            meta = extract_open_graph(link)
            saved.append(upsert_credential(student_id, meta, source=source))
        except Exception as exc:
            logger.warning("Skip link %s: %s", link, exc)
    if not saved and platform in {"coursera", "udemy"}:
        meta = extract_open_graph(profile_url, html=html)
        saved.append(upsert_credential(student_id, meta, source=source))
    return saved


def sync_platform(student_id: str, platform: str) -> dict:
    platform = platform.lower().strip()
    conn = _get_connection(student_id, platform)
    if not conn:
        raise ValueError(f"{platform} is not connected")

    token = conn.get("access_token") or ""
    extra: dict = {}
    try:
        extra = json.loads(conn.get("scopes") or "{}")
    except json.JSONDecodeError:
        extra = {}
    profile_url = extra.get("profile_url")

    imported: list[dict] = []
    if platform == "github":
        imported = _github_sync(student_id, token)
    elif platform in {"coursera", "udemy"}:
        if profile_url:
            imported = _profile_link_sync(student_id, platform, profile_url, platform)
        else:
            raise ValueError(f"Add a public {platform.title()} profile URL when connecting to discover certificates")
    else:
        raise ValueError(f"Sync not implemented for {platform}")

    stamp = now()
    with connect() as db:
        db.execute(
            "UPDATE student_integration_connections SET last_sync_at = ? WHERE student_id = ? AND platform = ?",
            (stamp, student_id, platform),
        )

    return {"platform": platform, "imported": len(imported), "credentials": imported, "synced_at": stamp}


def validate_integration_token(platform: str, token: str, profile_url: Optional[str] = None) -> str:
    platform = platform.lower()
    if platform == "github":
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        resp = requests.get("https://api.github.com/user", headers=headers, timeout=FETCH_TIMEOUT)
        if resp.status_code == 401:
            raise ValueError("GitHub rejected this token")
        resp.raise_for_status()
        return resp.json().get("login") or "github"
    if platform in {"coursera", "udemy"}:
        if not profile_url:
            raise ValueError(f"A public {platform.title()} profile URL is required alongside the token")
        _safe_fetch_html(profile_url)
        return profile_url
    raise ValueError("Unsupported platform")
