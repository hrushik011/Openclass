"""Google Gemini helpers for study Q&A and email drafting."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from ..db import connect

logger = logging.getLogger("openclass.ai")

_genai_client: Any = None


def get_genai_client():
    """Lazy-init Google GenAI client from GEMINI_API_KEY."""
    global _genai_client
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None
    if _genai_client is None:
        try:
            from google import genai

            _genai_client = genai.Client(api_key=api_key)
        except Exception as exc:
            logger.exception("Failed to initialize Gemini client: %s", exc)
            return None
    return _genai_client


def _clean_subject_name(raw: Optional[str]) -> str:
    text = str(raw or "").strip()
    return text or "General"


def gather_study_context(
    current_user: Optional[dict],
    *,
    subject: Optional[str] = None,
    extra_context: Optional[str] = None,
    max_notes: int = 14,
    max_assignments: int = 8,
) -> tuple[str, list[dict]]:
    """Build context string and source list from notes + assignments."""
    sources: list[dict] = []
    chunks: list[str] = []

    with connect() as db:
        sql = "SELECT id, title, subject, specialization, original_filename, faculty_name, created_at FROM lecture_notes"
        params: list = []
        if subject:
            sql += " WHERE subject = ?"
            params.append(subject)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max_notes)
        notes = [dict(r) for r in db.execute(sql, params).fetchall()]

        assign_sql = "SELECT id, title, subject, batch_id, deadline, description FROM assignments ORDER BY deadline ASC LIMIT ?"
        assignments = [dict(r) for r in db.execute(assign_sql, (max_assignments,)).fetchall()]

    for note in notes:
        subj = _clean_subject_name(note.get("subject"))
        title = note.get("title") or note.get("original_filename") or "Lecture note"
        spec = note.get("specialization") or "All Batches"
        faculty = note.get("faculty_name") or "Faculty"
        line = f"[Note #{note['id']}] {title} · {subj} · {spec} (uploaded by {faculty})"
        chunks.append(line)
        sources.append(
            {
                "type": "lecture_note",
                "id": note.get("id"),
                "title": title,
                "subject": subj,
                "batch": spec,
                "filename": note.get("original_filename"),
            }
        )

    for item in assignments:
        title = item.get("title") or "Assignment"
        subj = _clean_subject_name(item.get("subject"))
        deadline = item.get("deadline") or "TBD"
        desc = (item.get("description") or "").strip()
        snippet = desc[:400] + ("…" if len(desc) > 400 else "")
        line = f"[Assignment #{item['id']}] {title} · {subj} · due {deadline}"
        if snippet:
            line += f" — {snippet}"
        chunks.append(line)
        sources.append(
            {
                "type": "assignment",
                "id": item.get("id"),
                "title": title,
                "subject": subj,
                "deadline": deadline,
            }
        )

    if extra_context:
        chunks.append(f"[User context]\n{extra_context.strip()[:2000]}")

    role = str((current_user or {}).get("role") or "STUDENT").upper()
    name = (current_user or {}).get("name") or "Learner"
    batch = (current_user or {}).get("batch_id") or (current_user or {}).get("roll_no") or ""
    header = f"Learner: {name} ({role})" + (f", batch {batch}" if batch else "")
    body = "\n".join(chunks) if chunks else "No indexed lecture notes or assignments in Openclass yet."
    context = f"{header}\n\nCourse repository (cite by title when answering):\n{body}"
    return context, sources


def gemini_study_answer(query: str, context: str, sources: list[dict]) -> dict:
    client = get_genai_client()
    if not client:
        return {
            "configured": False,
            "answer": (
                "Openclass AI is not configured yet. Set **GEMINI_API_KEY** on the server to enable "
                "grounded answers from your lecture notes and syllabus."
            ),
            "sources": sources[:6],
        }

    prompt = f"""You are Openclass Study Assistant for a university learning platform.
Answer the student's question using ONLY the course context below when relevant.
If the context is insufficient, say what is missing and suggest checking Knowledge Hub notes.
Cite sources inline as [Note: title] or [Assignment: title].
Be concise, accurate, and study-focused.

Course context:
{context}

Student question:
{query.strip()}
"""
    try:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            contents=prompt,
        )
        text = (getattr(response, "text", None) or "").strip()
        if not text and getattr(response, "candidates", None):
            parts = response.candidates[0].content.parts
            text = "".join(getattr(p, "text", "") or "" for p in parts).strip()
        return {"configured": True, "answer": text or "No response from the model.", "sources": sources[:8]}
    except Exception as exc:
        logger.exception("Gemini ask failed: %s", exc)
        return {
            "configured": True,
            "answer": f"Could not reach the AI service: {exc}",
            "sources": sources[:6],
        }


def gemini_email_draft(bullets: str, signer_name: Optional[str] = None) -> dict:
    client = get_genai_client()
    signer = (signer_name or "Openclass User").strip()
    if not client:
        subject = "Request — " + (bullets.split("\n")[0][:60] if bullets else "Follow-up")
        body = (
            f"Dear Sir/Madam,\n\n"
            f"{bullets.strip()}\n\n"
            f"Thank you for your time and consideration.\n\n"
            f"Kind regards,\n{signer}\n"
            f"Sent via Openclass"
        )
        return {
            "configured": False,
            "subject": subject,
            "body": body,
            "sign_off": f"Kind regards,\n{signer}",
        }

    prompt = f"""Draft a professional institutional email from these bullet points.
Return ONLY valid JSON with keys: subject, body, sign_off (plain text strings).
Use formal but warm tone suitable for college email. Include greeting and proper sign-off for: {signer}.

Bullet points:
{bullets.strip()}
"""
    try:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            contents=prompt,
        )
        raw = (getattr(response, "text", None) or "").strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            data = json.loads(match.group(0))
            return {
                "configured": True,
                "subject": str(data.get("subject") or "Institutional request"),
                "body": str(data.get("body") or raw),
                "sign_off": str(data.get("sign_off") or f"Kind regards,\n{signer}"),
            }
        return {
            "configured": True,
            "subject": "Institutional correspondence",
            "body": raw,
            "sign_off": f"Kind regards,\n{signer}",
        }
    except Exception as exc:
        logger.exception("Gemini email draft failed: %s", exc)
        return {
            "configured": True,
            "subject": "Follow-up",
            "body": bullets.strip(),
            "sign_off": f"Kind regards,\n{signer}",
            "error": str(exc),
        }
