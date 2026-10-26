import base64
import json

import pytest

pytest.importorskip("firebase_admin")
cryptography = pytest.importorskip("cryptography")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from invigil.cloud import CloudConfig, FirebaseBackend, _inline_jpeg, open_sync  # noqa: E402
from invigil.db import Database  # noqa: E402


@pytest.fixture()
def fake_key(tmp_path):
    """A structurally valid service-account file. It authenticates nowhere, but it lets us
    exercise everything up to the first network call."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    p = tmp_path / "key.json"
    p.write_text(json.dumps({"type": "service_account", "project_id": "demo-proj", "private_key_id": "x",
                             "private_key": pem, "client_email": "sa@demo-proj.iam.gserviceaccount.com",
                             "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"}))
    return str(p)


def test_missing_key_file_gives_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="service account key"):
        FirebaseBackend(CloudConfig(credentials=str(tmp_path / "nope.json"), storage_bucket="b"))


def test_storage_mode_requires_bucket(fake_key):
    with pytest.raises(ValueError, match="storage_bucket"):
        FirebaseBackend(CloudConfig(credentials=fake_key, mode="storage"))


def test_backend_constructs_in_both_modes_and_can_be_reconfigured(fake_key):
    b1 = FirebaseBackend(CloudConfig(credentials=fake_key, storage_bucket="demo-proj.firebasestorage.app"))
    assert b1.bucket is not None and b1.bucket.name == "demo-proj.firebasestorage.app"
    b2 = FirebaseBackend(CloudConfig(credentials=fake_key, mode="firestore_inline"))  # re-init must not raise
    assert b2.bucket is None


def test_open_sync_never_raises(tmp_path, fake_key):
    db = Database(str(tmp_path / "t.db"))
    assert open_sync(db, tmp_path / "missing.json") == (None, "Not configured")
    bad = tmp_path / "firebase.json"
    CloudConfig(credentials=str(tmp_path / "nope.json")).save(bad)
    sync, msg = open_sync(db, bad)
    assert sync is None and "FileNotFoundError" in msg
    good = tmp_path / "ok.json"
    CloudConfig(credentials=fake_key, storage_bucket="demo-proj.firebasestorage.app").save(good)
    sync, msg = open_sync(db, good)
    assert sync is not None and "Connected" in msg


def test_inline_jpeg_is_small_valid_and_downscaled(tmp_path):
    img = (np.random.default_rng(0).random((1080, 1920, 3)) * 255).astype("uint8")
    p = tmp_path / "x.jpg"
    cv2.imwrite(str(p), img)
    raw = base64.b64decode(_inline_jpeg(str(p)))
    out = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    assert max(out.shape[:2]) == 720
    assert len(raw) < 700_000  # Firestore documents are capped at 1 MiB
