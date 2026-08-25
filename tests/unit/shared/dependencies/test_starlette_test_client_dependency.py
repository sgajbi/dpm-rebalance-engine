from __future__ import annotations

import subprocess
import sys

import httpx2


def test_fastapi_test_client_uses_supported_httpx2_without_deprecation_warning() -> None:
    probe = """
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx2
from starlette import testclient as starlette_testclient

app = FastAPI()

@app.get('/health')
def health() -> dict[str, bool]:
    return {'ok': True}

with TestClient(app) as client:
    response = client.get('/health')
assert response.status_code == 200
assert response.json() == {'ok': True}
assert httpx2.__version__ == '2.12.0'
assert starlette_testclient.httpx is httpx2
"""

    completed = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "FastAPI TestClient must use the governed httpx2 development dependency "
        "without deprecation warnings.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert httpx2.__version__ == "2.12.0"
