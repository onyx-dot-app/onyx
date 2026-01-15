#!/usr/bin/env python3
"""
Debug script to fetch usage limit overrides from the control plane.
Run this from within a data plane pod to diagnose usage limits issues.

Usage:
    python debug_usage_limits.py

Environment variables required:
    - DATA_PLANE_SECRET: Secret for generating JWT tokens
    - CONTROL_PLANE_API_BASE_URL: Base URL for the control plane API
"""

import json
import os
import sys
from datetime import datetime
from datetime import timedelta

import jwt
import requests


def generate_data_plane_token(secret: str) -> str:
    """Generate a JWT token for data plane authentication."""
    payload = {
        "iss": "data_plane",
        "exp": datetime.utcnow() + timedelta(minutes=5),
        "iat": datetime.utcnow(),
        "scope": "api_access",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def main() -> None:
    # Get required environment variables
    data_plane_secret = os.environ.get("DATA_PLANE_SECRET", "")
    control_plane_url = os.environ.get(
        "CONTROL_PLANE_API_BASE_URL", "http://localhost:8082"
    )

    print("=" * 60)
    print("Usage Limits Debug Script")
    print("=" * 60)
    print(f"CONTROL_PLANE_API_BASE_URL: {control_plane_url}")
    print(f"DATA_PLANE_SECRET set: {bool(data_plane_secret)}")
    print()

    if not data_plane_secret:
        print("ERROR: DATA_PLANE_SECRET is not set!")
        sys.exit(1)

    # Generate token
    try:
        token = generate_data_plane_token(data_plane_secret)
        print(f"Generated JWT token (first 50 chars): {token[:50]}...")
    except Exception as e:
        print(f"ERROR generating token: {e}")
        sys.exit(1)

    # Make request to usage-limit-overrides endpoint
    url = f"{control_plane_url}/usage-limit-overrides"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print(f"\nMaking request to: {url}")
    print(
        f"Headers: {json.dumps({k: v[:50] + '...' if k == 'Authorization' else v for k, v in headers.items()}, indent=2)}"
    )
    print()

    try:
        response = requests.get(url, headers=headers, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print()

        print("Response Body:")
        print("-" * 40)
        data = []
        try:
            data = response.json()
            print(json.dumps(data, indent=2))
        except json.JSONDecodeError:
            print(response.text)
        print("-" * 40)
        print("all tenant ids overridden:")
        for tenant_dct in data:  # should be a list of json
            print(tenant_dct["tenant_id"])

        if response.status_code != 200:
            print("\nWARNING: Non-200 status code received!")

    except requests.exceptions.ConnectionError as e:
        print(f"ERROR: Connection failed - {e}")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out after 30 seconds")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Request failed - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
