"""Secure API token storage using keyring"""

import keyring
import keyring.errors
import logging
import os
import sys
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

SERVICE_NAME = "interview_assistant_pro"
TOKEN_KEY    = "openai_api_token"


def _base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.join(os.path.dirname(__file__), "..")


def load_token():
    load_dotenv(os.path.join(_base_dir(), "config", ".env"))

    try:
        token = keyring.get_password(SERVICE_NAME, TOKEN_KEY)
        if token:
            return token
    except keyring.errors.KeyringError as e:
        logger.warning("Keyring read failed: %s", e)

    return os.getenv("OPENAI_API_TOKEN") or None


def save_token(token: str) -> bool:
    try:
        keyring.set_password(SERVICE_NAME, TOKEN_KEY, token)
        return True
    except Exception as e:
        print(f"Warning: Could not save token to keyring: {e}")
        return False


def delete_token():
    try:
        keyring.delete_password(SERVICE_NAME, TOKEN_KEY)
    except keyring.errors.KeyringError as e:
        logger.warning("Keyring delete failed: %s", e)
