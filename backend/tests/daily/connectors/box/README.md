# Box Connector Test Suite

## Overview

The Box connector test suite contains comprehensive integration tests for the Box connector. These tests validate that the connector properly:
- Authenticates with the Box API using JWT authentication
- Retrieves files and folders from Box
- Handles folder scoping and filtering
- Generates properly structured Onyx `Document` objects
- Handles batch processing and checkpointing
- Manages permissions and access control
- Supports nested folder traversal
- Handles error cases gracefully

## Prerequisites

1. **Box Enterprise Account**: You need a Box enterprise account with admin access
2. **Box JWT Application**: A Box application configured with JWT authentication
3. **Test Users**: At least one test user (test_user_1) is required for permission tests
4. **Python Environment**: Backend dependencies installed (see `backend/requirements`)
5. **Write Permissions**: The Box application must have write permissions to download files

## Setting Up Box JWT Application

### 1. Create a Box Application

1. Go to the [Box Developer Console](https://developer.box.com/)
2. Navigate to **My Apps** → **Create New App**
3. Select **Custom App** → **Server Authentication (with JWT)**
4. Give your app a name (e.g., "Onyx Box Connector Tests")

### 2. Configure Application Settings

1. In your app settings, go to the **Configuration** tab
2. **Important**: Enable **Write** permissions in the application scopes
   - This is required for the connector to download files
   - Without write permissions, file downloads will fail
3. Note your **Client ID** and **Client Secret** (you'll need these later)

### 3. Generate and Download JWT Configuration

1. In the **Configuration** tab, scroll to **Add and Manage Public Keys**
2. Click **Generate a Public/Private Keypair**
3. Download the **JSON configuration file** - this is your `config.json`
   - This file contains all the necessary authentication information
   - **Keep this file secure** - it contains sensitive credentials

### 4. Set Up User Access

1. In your Box enterprise admin console, go to **Users and Groups**
2. Create test users (at least `test_user_1`, optionally `test_user_2` and `test_user_3`)
3. Note the **User IDs** for each test user (you'll need these for impersonation)

### 5. Authorize the Application

1. In the Box Developer Console, go to your app's **Authorization** tab
2. Click **Review and Submit** to submit your app for authorization
3. Once authorized, you can use the JWT authentication

## Environment Variables

The test suite requires the following environment variables in `backend/.test.env`:

### Required (Admin User)

- **`BOX_JWT_CONFIG_JSON_STR`**: The JWT configuration JSON string
  - This is the content of the `config.json` file you downloaded
  - It should be a JSON string (may need to be escaped for the .env file)
  - Example format: `{"boxAppSettings": {...}, "enterpriseID": "..."}`

- **`BOX_PRIMARY_ADMIN_USER_ID`**: The Box user ID of the admin user
  - This is used for user impersonation
  - Find this in the Box admin console or via the Box API

### Optional (Test Users)

For full test coverage, you can also configure test user IDs for impersonation:

- **`BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_1`**: User ID for test_user_1 (required for permission tests)
- **`BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_2`**: User ID for test_user_2 (optional)
- **`BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_3`**: User ID for test_user_3 (optional)

**Note**: The same JWT config (`BOX_JWT_CONFIG_JSON_STR`) is used for all users. Box JWT authentication supports user impersonation, so you only need to provide different user IDs. Each user ID is used to impersonate that user when making API calls.

### Example `.test.env` File

```bash
# Box JWT Configuration (same config used for all users via impersonation)
BOX_JWT_CONFIG_JSON_STR="{\"boxAppSettings\":{...},\"enterpriseID\":\"...\"}"

# User IDs for impersonation
BOX_PRIMARY_ADMIN_USER_ID="12345678"

# Test User 1 (required for permission tests)
BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_1="12345679"

# Test User 2 (optional)
BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_2=""

# Test User 3 (optional)
BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_3=""
```

## Setting Up the Test Environment

### Automated Setup (Recommended)

We provide a script that automatically creates the required folder structure, test files, and permissions:

```bash
cd backend
python scripts/setup_box_test_env.py
```

This script will:
1. Read credentials from `.test.env`
2. Create the required folder structure (Folder 1, Folder 2, Folder 3, etc.)
3. Create test files with proper naming (`file_0.txt`, `file_1.txt`, etc.)
4. Set up sharing and permissions between users
5. Update `consts_and_utils.py` with actual folder and user IDs

**Note**: The script requires write permissions in your Box account. Make sure your JWT application has write access enabled.

### Manual Setup

If you prefer to set up manually, you'll need to:

1. Create the following folder structure in your Box account:
   ```
   Root/
   ├── file_0.txt through file_4.txt (admin files)
   ├── file_5.txt through file_9.txt (test_user_1 files)
   ├── Folder 1/
   │   ├── file_25.txt through file_29.txt
   │   ├── Folder 1-1/
   │   │   └── file_30.txt through file_34.txt
   │   └── Folder 1-2/ (public folder)
   │       └── file_35.txt through file_39.txt
   ├── Folder 2/
   │   ├── file_45.txt through file_49.txt
   │   ├── Folder 2-1/
   │   │   └── file_50.txt through file_54.txt
   │   └── Folder 2-2/
   │       └── file_55.txt through file_59.txt
   ├── Folder 3/
   │   └── file_62.txt through file_64.txt
   └── Sections Folder/
       └── file_61.txt (special content)
   ```

2. Create files with naming pattern: `file_{id}.txt` with content: `This is file {id}`
3. Set up sharing permissions as defined in `consts_and_utils.py` (see `ACCESS_MAPPING`)
4. Update `consts_and_utils.py` with actual folder IDs and user IDs

## Running the Tests

### Prerequisites

Before running tests, ensure:
1. Your `.test.env` file is configured with valid credentials
2. The test environment has been set up (either via script or manually)
3. You're in the `backend/` directory

### Run All Box Connector Tests

```bash
cd backend
pytest -v -s tests/daily/connectors/box/
```

### Run Specific Test Files

```bash
# Run basic connector tests
pytest -v -s tests/daily/connectors/box/test_basic.py

# Run permission tests
pytest -v -s tests/daily/connectors/box/test_permissions.py

# Run permission sync tests
pytest -v -s tests/daily/connectors/box/test_perm_sync.py
```

### Run Specific Test Functions

```bash
# Run a specific test
pytest -v -s tests/daily/connectors/box/test_basic.py::test_include_all_files

# Run tests matching a pattern
pytest -v -s tests/daily/connectors/box/ -k "permission"
```

### Run Tests Without Skipped Tests

Some tests are marked with `@pytest.mark.skip` if they require additional setup:

```bash
# Run all tests, including skipped ones (will fail if not properly configured)
pytest -v -s tests/daily/connectors/box/ --run-skipped
```

## Test Structure

### Test Files

- **`test_basic.py`**: Basic connector functionality tests
  - Folder traversal
  - File retrieval
  - Folder scoping
  - Checkpointing
  - Size thresholds

- **`test_permissions.py`**: Permission and access control tests
  - User access mapping
  - Public file access
  - Restricted access
  - Collaboration permissions
  - Shared folders

- **`test_perm_sync.py`**: Permission synchronization tests
  - Permission extraction
  - Access control validation

- **`test_box_basic.py`**: Basic initialization tests (currently skipped)

### Test Constants

The `consts_and_utils.py` file contains:
- File ID ranges for different test scenarios
- Folder IDs (should match actual Box folder IDs)
- User IDs (should match actual Box user IDs)
- Access mapping (defines which users can access which files)
- Helper functions for assertions and document loading

**Important**: After running the setup script or manual setup, the folder IDs and user IDs in `consts_and_utils.py` should be updated with actual values from your Box account.

## Troubleshooting

### Authentication Errors

- **"Failed to initialize Box JWT authentication"**
  - Verify your `BOX_JWT_CONFIG_JSON_STR` is correctly formatted
  - Ensure the JSON string is properly escaped in `.test.env`
  - Check that the JWT application is authorized

- **"User ID missing"**
  - Verify `BOX_PRIMARY_ADMIN_USER_ID` is set correctly
  - Ensure the user ID exists in your Box enterprise

### Permission Errors

- **"Insufficient permissions"**
  - Ensure your Box JWT application has **Write** permissions enabled
  - Check that the application is authorized in your Box enterprise
  - Verify user impersonation is working correctly

### File Not Found Errors

- **"File not found" or "Folder not found"**
  - Run the setup script to create the test environment
  - Verify folder IDs in `consts_and_utils.py` match actual Box folder IDs
  - Check that files were created with the correct naming pattern

### Test Failures

- **Tests fail with "expected file IDs not found"**
  - Ensure the test environment was set up correctly
  - Verify file naming matches the pattern: `file_{id}.txt`
  - Check that file content matches: `This is file {id}`
  - Run the setup script again to recreate the environment

## Additional Resources

- [Box Developer Documentation](https://developer.box.com/)
- [Box Python SDK Documentation](https://github.com/box/box-python-sdk-gen)
- [Box JWT Authentication Guide](https://developer.box.com/guides/authentication/jwt/jwt-setup/)

## Notes

- The test environment creates a significant number of files and folders. Consider using a dedicated Box enterprise or test account.
- Some tests require multiple users for full coverage. At minimum, `test_user_1` is required for permission tests.
- The setup script is idempotent - you can run it multiple times, but it will create duplicate files if folders already exist.
- File IDs in the tests are placeholders. The actual file IDs in Box will be different, but the connector uses file names for matching.
