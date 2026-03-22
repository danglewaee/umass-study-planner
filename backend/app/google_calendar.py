from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from .models import CommitmentKind, FixedCommitmentInput, GoogleCalendarSummary

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
GOOGLE_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"


@dataclass(frozen=True)
class GoogleCalendarSettings:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    scopes: tuple[str, ...] = (
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.readonly",
    )

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


@dataclass(frozen=True)
class GoogleTokenBundle:
    access_token: str
    refresh_token: str | None
    scope: str
    expires_at: datetime | None


@dataclass(frozen=True)
class ImportedCommitmentCandidate:
    commitment: FixedCommitmentInput
    source_ref: str


def settings() -> GoogleCalendarSettings:
    return GoogleCalendarSettings(
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        redirect_uri=os.getenv("GOOGLE_REDIRECT_URI"),
    )


def build_authorization_url(state: str) -> str:
    config = settings()
    if not config.is_configured():
        raise RuntimeError("Google Calendar integration is not configured.")

    query = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(config.scopes),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GOOGLE_AUTH_URL}?{query}"


def exchange_code_for_tokens(code: str) -> GoogleTokenBundle:
    config = settings()
    if not config.is_configured():
        raise RuntimeError("Google Calendar integration is not configured.")

    response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    response.raise_for_status()
    return _token_bundle_from_payload(response.json())


def refresh_access_token(refresh_token: str) -> GoogleTokenBundle:
    config = settings()
    if not config.is_configured():
        raise RuntimeError("Google Calendar integration is not configured.")

    response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    payload["refresh_token"] = refresh_token
    return _token_bundle_from_payload(payload)


def fetch_connected_email(access_token: str) -> str:
    response = _google_request(
        "GET",
        GOOGLE_USERINFO_URL,
        access_token,
    )
    email = response.json().get("email")
    if not email:
        raise RuntimeError("Google user info response did not include an email address.")
    return email


def list_calendars(access_token: str) -> list[GoogleCalendarSummary]:
    response = _google_request("GET", GOOGLE_CALENDAR_LIST_URL, access_token)
    payload = response.json()
    items = payload.get("items", [])
    return [
        GoogleCalendarSummary(
            id=item["id"],
            summary=item.get("summaryOverride") or item.get("summary") or item["id"],
            primary=bool(item.get("primary")),
            access_role=item.get("accessRole", "reader"),
            time_zone=item.get("timeZone"),
        )
        for item in items
    ]


def list_events(access_token: str, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
    url = GOOGLE_CALENDAR_EVENTS_URL.format(calendar_id=quote(calendar_id, safe=""))
    response = _google_request(
        "GET",
        url,
        access_token,
        params={
            "timeMin": _to_google_timestamp(time_min),
            "timeMax": _to_google_timestamp(time_max),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
        },
    )
    return response.json().get("items", [])


def infer_weekly_commitments(events: list[dict[str, Any]]) -> tuple[list[ImportedCommitmentCandidate], int]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    skipped_events = 0

    for event in events:
        start_raw = event.get("start", {})
        end_raw = event.get("end", {})
        if "dateTime" not in start_raw or "dateTime" not in end_raw:
            skipped_events += 1
            continue

        start_at = _parse_google_datetime(start_raw["dateTime"])
        end_at = _parse_google_datetime(end_raw["dateTime"])
        if end_at <= start_at:
            skipped_events += 1
            continue

        source_key = event.get("recurringEventId") or _normalized_event_key(event, start_at, end_at)
        buckets.setdefault(source_key, []).append(
            {
                "summary": event.get("summary") or "Google Calendar event",
                "location": event.get("location") or "",
                "start_at": start_at,
                "end_at": end_at,
                "source_key": source_key,
                "is_explicitly_recurring": bool(event.get("recurringEventId") or event.get("recurrence")),
            }
        )

    candidates: list[ImportedCommitmentCandidate] = []
    for bucket in buckets.values():
        sample = bucket[0]
        if len(bucket) < 2 and not sample["is_explicitly_recurring"]:
            skipped_events += len(bucket)
            continue

        commitment = FixedCommitmentInput(
            title=str(sample["summary"])[:120],
            day_of_week=sample["start_at"].weekday(),
            start=sample["start_at"].time().replace(second=0, microsecond=0),
            end=sample["end_at"].time().replace(second=0, microsecond=0),
            kind=_guess_commitment_kind(str(sample["summary"])),
            location=str(sample["location"])[:120],
            notes="Imported from Google Calendar.",
        )
        candidates.append(ImportedCommitmentCandidate(commitment=commitment, source_ref=str(sample["source_key"])))

    candidates.sort(key=lambda item: (item.commitment.day_of_week, item.commitment.start, item.commitment.title.lower()))
    return candidates, skipped_events


def _google_request(
    method: str,
    url: str,
    access_token: str,
    *,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    response = httpx.request(
        method,
        url,
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    response.raise_for_status()
    return response


def _token_bundle_from_payload(payload: dict[str, Any]) -> GoogleTokenBundle:
    expires_in = payload.get("expires_in")
    expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
    return GoogleTokenBundle(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        scope=payload.get("scope", ""),
        expires_at=expires_at,
    )


def _to_google_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_google_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _normalized_event_key(event: dict[str, Any], start_at: datetime, end_at: datetime) -> str:
    summary = (event.get("summary") or "google-calendar-event").strip().lower()
    return "|".join(
        [
            summary,
            str(start_at.weekday()),
            start_at.time().replace(second=0, microsecond=0).isoformat(),
            end_at.time().replace(second=0, microsecond=0).isoformat(),
        ]
    )


def _guess_commitment_kind(summary: str) -> CommitmentKind:
    lowered = summary.lower()
    if "gym" in lowered or "workout" in lowered or "therapy" in lowered:
        return CommitmentKind.health
    if "club" in lowered or "meeting" in lowered:
        return CommitmentKind.club
    if "shift" in lowered or "work" in lowered or "job" in lowered:
        return CommitmentKind.work
    if "commute" in lowered or "bus" in lowered or "train" in lowered:
        return CommitmentKind.commute
    return CommitmentKind.class_session
