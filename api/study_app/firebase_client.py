"""Firebase Admin / Firestore client setup, including the local emulator path."""

from __future__ import annotations

import firebase_admin
from firebase_admin import credentials, firestore
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore as gcloud_firestore

from .config import (
    FIREBASE_CLIENT_EMAIL,
    FIREBASE_PRIVATE_KEY,
    FIREBASE_PROJECT_ID,
    USING_FIREBASE_EMULATOR,
)


def firebase_configured() -> bool:
    return USING_FIREBASE_EMULATOR or bool(
        FIREBASE_PROJECT_ID and FIREBASE_CLIENT_EMAIL and FIREBASE_PRIVATE_KEY
    )


def get_firebase_app() -> firebase_admin.App | None:
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    if USING_FIREBASE_EMULATOR:
        return firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID or "demo-study-app"})

    if not firebase_configured():
        return None

    cred = credentials.Certificate(
        {
            "type": "service_account",
            "project_id": FIREBASE_PROJECT_ID,
            "client_email": FIREBASE_CLIENT_EMAIL,
            "private_key": FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    return firebase_admin.initialize_app(cred)


_emulator_firestore_client: gcloud_firestore.Client | None = None


def get_firestore_client():
    global _emulator_firestore_client

    if USING_FIREBASE_EMULATOR:
        # firebase_admin.firestore.client() eagerly resolves real Google
        # Application Default Credentials even when talking to the emulator,
        # which fails wherever ADC isn't configured. Anonymous credentials
        # sidestep that — the emulator never checks them anyway.
        if _emulator_firestore_client is None:
            _emulator_firestore_client = gcloud_firestore.Client(
                project=FIREBASE_PROJECT_ID or "demo-study-app",
                credentials=AnonymousCredentials(),
            )
        return _emulator_firestore_client

    app_instance = get_firebase_app()
    return firestore.client(app_instance) if app_instance else None
