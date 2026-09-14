"""Direct Google Meet REST API integration."""

import json

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

MEET_CREATE_URL = "https://meet.googleapis.com/v2/spaces"

def create_meeting_space(credentials_json_str: str) -> dict:
    """Create a Google Meet space."""
    cred_info = json.loads(credentials_json_str)
    credentials = Credentials.from_authorized_user_info(cred_info)
    session = AuthorizedSession(credentials)
    
    # Send an empty JSON payload for standard meeting space creation
    response = session.post(MEET_CREATE_URL, json={}, timeout=20)
    response.raise_for_status()
    data = response.json()
    
    if not data.get("name") or not data.get("meetingUri"):
        raise RuntimeError("Google Meet API did not return a meeting space name or URL")
        
    return {
        "space_id": data["name"], 
        "meeting_url": data["meetingUri"]
    }