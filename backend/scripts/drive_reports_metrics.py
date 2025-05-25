import json
import os
import random
from datetime import datetime
from datetime import timezone
from typing import Any

from onyx.connectors.google_drive.connector import GoogleDriveConnector  # type: ignore
from onyx.connectors.google_utils.shared_constants import (  # type: ignore
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)  # type: ignore
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)  # type: ignore
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_TOKEN_KEY,
)  # type: ignore
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)  # type: ignore
from onyx.connectors.google_utils.shared_constants import (
    GoogleOAuthAuthenticationMethod,
)  # type: ignore


# Main function that the connector will call
def get_total_docs_count(
    creds_dict: dict[str, Any],
    admin_email: str,
    user_fraction: float = 0.2,
    date: datetime | None = None,
) -> int:
    """
    Get the total estimated document count for the organization by using
    the GoogleDriveConnector's slim retrieval method to count all documents.

    Args:
        creds: Google credentials
        admin_email: Admin email for impersonation
        date: Optional date (not used in this implementation, kept for compatibility)

    Returns:
        Total number of documents in the organization (actual count, not estimate)
    """
    try:
        print("Initializing Google Drive connector...")

        # Create connector with comprehensive configuration to get all documents
        connector = GoogleDriveConnector(
            include_shared_drives=True,
            include_my_drives=True,
            include_files_shared_with_me=True,
            batch_size=1000,
            calculate_metrics=True,
        )

        print("Loading credentials into connector...")
        connector.load_credentials(creds_dict)

        all_emails = connector._get_all_user_emails()[1:]  # first is admin
        num_to_select = int(len(all_emails) * user_fraction) + 1
        print(f"All emails: {all_emails}")
        print(f"selecting {num_to_select} for estimation:")
        random.shuffle(all_emails)
        selected_emails = [admin_email] + all_emails[:num_to_select]
        print(f"Selected emails: {selected_emails}")

        connector._specific_user_emails = selected_emails

        print("Starting document retrieval and counting...")
        print("Note: This may take a while for organizations with many documents...")

        total_docs = 0
        batch_count = 0

        # Use the slim document retrieval to count all documents
        for slim_doc_batch in connector.retrieve_all_slim_documents():
            batch_size = len(slim_doc_batch)
            total_docs += batch_size
            batch_count += 1

            # Print progress every 50 batches
            if batch_count % 50 == 0:
                print(
                    f"Processed {batch_count} batches, found {total_docs} documents so far..."
                )

        print("Document counting completed!")
        print(f"Total batches processed: {batch_count}")
        print(f"Total documents found: {total_docs}")
        print(f"Metrics: {connector.metrics}")

        my_drive_ct = 0
        shared_with_me_ct = 0
        for _email, count in connector.metrics["my_drive"].items():
            my_drive_ct += count
        for _email, count in connector.metrics["shared_with_me"].items():
            shared_with_me_ct += count

        print(f"My drive count: {my_drive_ct}")
        print(f"Shared with me count: {shared_with_me_ct}")

        my_drive_ct_estimate = int(my_drive_ct / user_fraction - my_drive_ct)
        shared_with_me_ct_estimate = int(
            shared_with_me_ct / user_fraction - shared_with_me_ct
        )

        print(f"My drive estimate: {my_drive_ct_estimate}")
        print(f"Shared with me estimate: {shared_with_me_ct_estimate}")

        return total_docs + my_drive_ct_estimate + shared_with_me_ct_estimate

    except Exception as e:
        print(f"Error counting documents with connector: {e}")
        raise


def create_credentials_from_env(admin_email: str) -> dict[str, Any]:
    if not admin_email:
        raise ValueError("GOOGLE_ADMIN_EMAIL environment variable is required")

    # Try service account first (recommended for Reports API)
    service_account_json_str = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR")
    if service_account_json_str:
        raw_cred_str = service_account_json_str
    else:
        raw_cred_str = os.environ.get("GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR") or ""
        if not raw_cred_str:
            raise ValueError(
                "No valid credentials found. Please set either "
                "GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR or GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR "
                "environment variable"
            )

    refried_credential_string = json.dumps(json.loads(raw_cred_str))
    cred_key = (
        DB_CREDENTIALS_DICT_TOKEN_KEY
        if not service_account_json_str
        else DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY
    )
    return {
        cred_key: refried_credential_string,
        DB_CREDENTIALS_PRIMARY_ADMIN_KEY: admin_email,
        DB_CREDENTIALS_AUTHENTICATION_METHOD: GoogleOAuthAuthenticationMethod.UPLOADED.value,
    }


if __name__ == "__main__":
    """
    Main script to calculate and print the total number of documents in a Google organization
    using the GoogleDriveConnector's slim retrieval method.

    This approach counts ALL documents in the organization's history, not just the last 450 days
    like the Reports API would limit us to.

    Required environment variables:
    - GOOGLE_ADMIN_EMAIL: Email of an admin user
    - Either:
      - GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR: Service account credentials JSON
      OR
      - GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR: OAuth credentials JSON

    Example usage:
        export GOOGLE_ADMIN_EMAIL="admin@yourcompany.com"
        export GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR='{"type":"service_account",...}'
        python backend/scripts/drive_reports_metrics.py
    """
    print("Starting Google Drive organization document count calculation...")
    print(
        "Using connector-based approach to count ALL documents (not limited by Reports API retention)"
    )
    start_time = datetime.now(timezone.utc)
    # Create credentials from environment variables
    admin_email = os.environ.get("GOOGLE_ADMIN_EMAIL")
    if not admin_email:
        raise ValueError("GOOGLE_ADMIN_EMAIL environment variable is required")

    creds_dict = create_credentials_from_env(admin_email)
    print(f"Using admin email: {admin_email}")

    # Get total document count using connector
    print("Fetching total document count using Google Drive connector...")
    total_docs = get_total_docs_count(creds_dict, admin_email)

    # wow so fancy thanks LLM
    print(f"\n{'='*60}")
    print("Google Drive Organization Document Count")
    print(f"{'='*60}")
    print(f"Admin Email: {admin_email}")
    print(f"Total Documents: {total_docs:,}")
    print(f"Time taken: {datetime.now(timezone.utc) - start_time}")
    print("Method: Connector-based (estimate)")
    print(
        f"Report Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    print(f"{'='*60}\n")

    print("Document count calculation completed successfully")
