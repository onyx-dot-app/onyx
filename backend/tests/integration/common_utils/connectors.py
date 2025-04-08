import io

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser


def upload_file(
    file_path: str, file_name: str, user_performing_action: DATestUser
) -> dict:
    """
    Upload a file to create a file connector.

    Args:
        file_path: Path to the file to upload
        file_name: Name to use for the file
        user_performing_action: User performing the action

    Returns:
        dict: Response containing file paths and connector information
    """

    # Read the file content
    with open(file_path, "rb") as f:
        file_content = f.read()

    # Create a file-like object
    file_obj = io.BytesIO(file_content)

    # The 'files' form field expects a list of files
    files = [("files", (file_name, file_obj, "application/octet-stream"))]

    # Use the user's headers but without Content-Type
    # as requests will set the correct multipart/form-data Content-Type for us
    headers = user_performing_action.headers.copy()
    if "Content-Type" in headers:
        del headers["Content-Type"]

    # Print debug info
    print(f"Uploading file: {file_path} with name: {file_name}")
    print(f"Headers: {headers}")

    # Make the request
    response = requests.post(
        f"{API_SERVER_URL}/manage/admin/connector/file/upload",
        files=files,
        headers=headers,
    )

    # Print detailed response for debugging
    print(f"Response status: {response.status_code}")
    print(f"Response text: {response.text}")

    if not response.ok:
        try:
            error_detail = response.json().get("detail", "Unknown error")
            print(f"Error detail: {error_detail}")
        except Exception as e:
            error_detail = response.text
            print(f"Failed to parse error as JSON: {e}")

        raise Exception(
            f"Unable to upload files - {error_detail} (Status code: {response.status_code})"
        )

    response_json = response.json()
    print(f"Response JSON: {response_json}")
    return response_json
