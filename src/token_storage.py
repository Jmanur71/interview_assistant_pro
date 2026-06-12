"""Secure API token storage using keyring"""

import keyring
import keyring.errors
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

SERVICE_NAME = "interview_assistant_pro"
TOKEN_KEY = "openai_api_token"


def load_token():
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

    try:
        token = keyring.get_password(SERVICE_NAME, TOKEN_KEY)
        if token:
            return token
    except keyring.errors.KeyringError as e:
        logger.warning("Keyring read failed: %s", e)

    token = os.getenv("OPENAI_API_TOKEN")
    if token:
        return token

    return None


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