# Coda Connector Test Suite

## Overview

The `test_coda_connector.py` file contains comprehensive integration tests for the Coda connector. These tests validate that the connector properly:
- Authenticates with the Coda API
- Retrieves documents, pages, and tables
- Generates properly structured Onyx `Document` objects
- Handles batch processing correctly
- Supports workspace scoping
- Polls for recent updates
- Handles error cases gracefully

## Prerequisites

1. **Coda API Access**: You need a valid Coda account with at least one workspace containing documents, pages, or tables
2. **Coda Bearer Token**: Generate an API token from your Coda account settings
3. **Python Environment**: Backend dependencies installed (see backend/requirements)
4. **Test Data**: Ideally, your Coda workspace should have:
   - At least one document
   - At least one page within a document
   - At least one table within a document

## Environment Variables

The test suite requires the following environment variables:

### Required
- **`CODA_BEARER_TOKEN`**: Your Coda API bearer token
  - Get this from: Coda Account Settings → API Settings → Generate API Token
  - Without this, tests will be skipped

### Optional
- **`CODA_BASE_URL`**: The Coda API base URL
  - Default: `https://coda.io/apis/v1`
  - Only override if using a different API endpoint

- **`CODA_WORKSPACE_ID`**: A specific workspace ID to test workspace scoping
  - If not provided, workspace-scoped tests will be skipped
  - Find this by inspecting the Coda API response or your workspace URL

## Running the Tests

### Method 1: Run All Tests in the File

From the `backend/` directory:

```bash
# Set environment variables and run all tests
export CODA_BEARER_TOKEN="your_token_here"
pytest -v -s tests/daily/connectors/coda/test_coda_connector.py
```

### Method 2: Run a Specific Test Class

```bash
# Run only validation tests
export CODA_BEARER_TOKEN="your_token_here"
pytest -v -s tests/daily/connectors/coda/test_coda_connector.py::TestCodaConnectorValidation

# Run only load_from_state tests
pytest -v -s tests/daily/connectors/coda/test_coda_connector.py::TestLoadFromState
```

### Method 3: Run a Single Test

```bash
# Run a specific test function
export CODA_BEARER_TOKEN="your_token_here"
pytest -v -s tests/daily/connectors/coda/test_coda_connector.py::TestLoadFromState::test_document_count_matches_expected
```

### Method 4: Using an Environment File

Create a `.env` file in `backend/tests/daily/connectors/coda/`:

```bash
# .env
CODA_BEARER_TOKEN=your_token_here
CODA_WORKSPACE_ID=your_workspace_id  # Optional
```

Then run with dotenv:

```bash
cd backend
python -m dotenv -f tests/daily/connectors/coda/.env run -- pytest -v -s tests/daily/connectors/coda/test_coda_connector.py
```

### Method 5: Direct Execution

The test file can be run directly:

```bash
export CODA_BEARER_TOKEN="your_token_here"
cd backend/tests/daily/connectors/coda
python test_coda_connector.py
```

## Test Structure

### Test Classes

1. **`TestCodaConnectorValidation`**
   - Validates connector settings and credentials
   - Tests authentication success and failure cases
   - Tests workspace-scoped connector validation

2. **`TestLoadFromState`**
   - Tests full document retrieval via `load_from_state()`
   - Validates batch sizes, document counts, and structure
   - Checks document fields, metadata, and content
   - Verifies both page and table document generation
   - Tests the `index_page_content` configuration flag

3. **`TestPollSource`**
   - Tests incremental updates via `poll_source()`
   - Validates time-range filtering
   - Checks that only updated documents are returned

4. **`TestWorkspaceScoping`**
   - Tests the `workspace_id` filtering functionality
   - Validates that scoped connectors only retrieve documents from the specified workspace

5. **`TestErrorHandling`**
   - Tests graceful handling of edge cases
   - Validates behavior with inaccessible content or empty tables

## Common Test Patterns

### Fixtures

The test suite uses pytest fixtures for setup:

- **`coda_credentials`**: Loads and validates credentials from environment variables
- **`connector`**: Creates a standard CodaConnector instance
- **`workspace_scoped_connector`**: Creates a workspace-scoped connector (if `CODA_WORKSPACE_ID` is set)
- **`reference_data`**: Fetches ground truth data from the Coda API for validation

### Skipped Tests

Tests are automatically skipped when:
- `CODA_BEARER_TOKEN` is not set
- `CODA_WORKSPACE_ID` is not set (for workspace-scoped tests)
- No documents, pages, or tables are found in the workspace

## Troubleshooting

### Tests are Skipped

**Issue**: Tests show as "SKIPPED" instead of running

**Solutions**:
- Ensure `CODA_BEARER_TOKEN` is set and valid
- Verify your Coda workspace has at least one document with pages or tables
- For workspace tests, ensure `CODA_WORKSPACE_ID` is set

### Authentication Errors

**Issue**: Tests fail with authentication errors

**Solutions**:
- Verify your bearer token is valid and hasn't expired
- Check that the token has appropriate API permissions
- Ensure you're not hitting API rate limits

### Document Count Mismatches

**Issue**: Tests fail with "Expected X documents but got Y"

**Possible Causes**:
- API rate limiting causing partial data retrieval
- Network issues during test execution
- Changes to workspace data during test execution
- Permission issues preventing access to some documents

### Empty Content Errors

**Issue**: Tests fail due to empty document content

**Possible Causes**:
- Pages without accessible content (permission issues)
- Empty tables or pages in your workspace
- The `index_page_content` flag set incorrectly

## Test Execution Tips

1. **Run tests during low-traffic times**: API rate limits may affect test reliability
2. **Use a dedicated test workspace**: Avoid running tests on production workspaces with changing data
3. **Check test output verbosity**: Use `-v` for verbose test names, `-s` to see print statements
4. **Isolate failing tests**: Run specific test classes or functions to debug issues
5. **Review fixture output**: The `reference_data` fixture prints warnings about API access issues

## CI/CD Integration

When integrating these tests into CI/CD pipelines:

```yaml
# Example GitHub Actions configuration
- name: Run Coda Connector Tests
  env:
    CODA_BEARER_TOKEN: ${{ secrets.CODA_BEARER_TOKEN }}
    CODA_WORKSPACE_ID: ${{ secrets.CODA_WORKSPACE_ID }}
  run: |
    cd backend
    pytest -v tests/daily/connectors/coda/test_coda_connector.py
```

Store credentials as encrypted secrets in your CI/CD platform.

## Expected Test Duration

- Full test suite: ~30-60 seconds (depending on workspace size and API latency)
- Individual test classes: ~5-15 seconds
- Validation tests: <5 seconds

## Additional Resources

- [Coda API Documentation](https://coda.io/developers/apis/v1)
- [Onyx Connector Documentation](../../../../onyx/connectors/README.md)
- [pytest Documentation](https://docs.pytest.org/)
