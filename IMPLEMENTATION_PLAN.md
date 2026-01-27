# Implementation Plan: Jira Service Management Connector

## Issue
[#2281](https://github.com/onyx-dot-app/onyx/issues/2281) - Jira Service Management Connector

## Branch
**Branch Name**: `feature/2281-jira-service-management-connector`

**Create Branch:**
```bash
git checkout -b feature/2281-jira-service-management-connector
```

## Objective
Create a new connector that pulls all tickets from a specified Jira Service Management (JSM) project. JSM is a specialized version of Jira for IT service management, customer support, and operations. While it uses the same underlying Jira REST API, it has specific project types and issue types (Incident, Request, Problem, Change, etc.).

## Background

### What is Jira Service Management?
- JSM is an extension of Jira designed for IT service management (ITSM) and customer support
- Uses the same REST API as regular Jira, but with service management-specific features
- Projects are configured as "Service Management" projects
- Issue types include: Incident, Service Request, Problem, Change, etc.
- May have customer-facing portals for self-service

### Existing Implementation
- There is already a fully-featured `JiraConnector` that:
  - Supports both Jira Cloud (v3 API) and Server/Data Center (v2 API)
  - Implements `CheckpointedConnectorWithPermSync` and `SlimConnectorWithPermSync`
  - Uses JQL queries to fetch issues
  - Processes issues into documents with comprehensive metadata
  - Located at: `backend/onyx/connectors/jira/connector.py`

### Approach
Since JSM uses the same Jira API, we can leverage the existing Jira connector infrastructure while creating a specialized connector that:
1. Targets JSM projects specifically
2. May include JSM-specific metadata (e.g., customer portal information, SLA data)
3. Has a distinct `DocumentSource` enum value for proper categorization

## Implementation Steps

### Phase 1: Backend Core Implementation

#### 1.1 Add DocumentSource Enum Value
**File**: `backend/onyx/configs/constants.py`

- [ ] Add `JIRA_SERVICE_MANAGEMENT = "jira_service_management"` to the `DocumentSource` enum (around line 178, after `JIRA`)

**Example:**
```python
JIRA = "jira"
JIRA_SERVICE_MANAGEMENT = "jira_service_management"  # New entry
SLAB = "slab"
```

#### 1.2 Create JSM Connector Module
**Directory**: `backend/onyx/connectors/jira_service_management/`

Create the following files:
- `__init__.py` - Module initialization
- `connector.py` - Main connector implementation
- `utils.py` - JSM-specific utilities (if needed)

**Implementation Strategy:**
- [ ] Create `JiraServiceManagementConnector` class that extends or reuses the existing `JiraConnector` logic
- [ ] Key differences from regular Jira connector:
  - Constructor should accept a `jsm_project_key` parameter (JSM project key)
  - JQL query should filter for the specific JSM project: `project = "PROJECT_KEY"`
  - Optionally filter by JSM-specific issue types (Incident, Request, Problem, Change)
  - May add JSM-specific metadata fields (SLA information, customer portal links, etc.)
- [ ] Inherit from `CheckpointedConnectorWithPermSync` and `SlimConnectorWithPermSync` (same as JiraConnector)
- [ ] Reuse existing utilities from `backend/onyx/connectors/jira/utils.py` and `backend/onyx/connectors/jira/access.py`

**Key Implementation Details:**
```python
from onyx.connectors.jira.connector import (
    JiraConnectorCheckpoint,
    _perform_jql_search,
    process_jira_issue,
    # ... other reusable components
)
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync, SlimConnectorWithPermSync
from onyx.configs.constants import DocumentSource

class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JiraConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        jira_base_url: str,
        jsm_project_key: str,  # Specific to JSM projects
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        # Optional: filter by JSM issue types
        include_issue_types: list[str] | None = None,  # e.g., ["Incident", "Service Request"]
    ) -> None:
        # Initialize similar to JiraConnector but with JSM-specific config
```

#### 1.3 Register Connector in Registry
**File**: `backend/onyx/connectors/registry.py`

- [ ] Add mapping entry to `CONNECTOR_CLASS_MAP`:
```python
DocumentSource.JIRA_SERVICE_MANAGEMENT: ConnectorMapping(
    module_path="onyx.connectors.jira_service_management.connector",
    class_name="JiraServiceManagementConnector",
),
```

#### 1.4 Update Factory (if needed)
**File**: `backend/onyx/connectors/factory.py`

- [ ] Verify that the existing factory logic works with the new connector (should work automatically via registry)

### Phase 2: Frontend Integration

#### 2.1 Add Source Metadata
**File**: `web/src/lib/sources.ts`

- [ ] Add `jira_service_management` entry to `SOURCE_METADATA_MAP`:
```typescript
jira_service_management: {
  icon: JiraIcon,  // Reuse Jira icon or create JSM-specific icon
  displayName: "Jira Service Management",
  category: SourceCategory.TicketingAndTaskManagement,
  docs: `${DOCS_ADMINS_PATH}/connectors/official/jira-service-management`,
  isPopular: false,  // Set to true if this becomes popular
},
```

- [ ] Import `JiraIcon` if not already imported (or create `JiraServiceManagementIcon`)

#### 2.2 Add Connector Configuration Form
**File**: `web/src/lib/connectors/connectors.ts`

- [ ] Add connector configuration to `connectorConfigs` object:
```typescript
jira_service_management: {
  name: "Jira Service Management",
  source: "jira_service_management",
  connectorSpecificConfig: {
    jira_base_url: {
      type: "string",
      required: true,
    },
    jsm_project_key: {
      type: "string",
      required: true,
    },
    comment_email_blacklist: {
      type: "list",
      required: false,
    },
    labels_to_skip: {
      type: "list",
      required: false,
    },
  },
  credentialNames: ["jira_user_email", "jira_api_token"],  // Reuse Jira credentials
},
```

#### 2.3 Create Connector Form Component (if needed)
**File**: `web/src/lib/connectors/[connector-folder]/JiraServiceManagementConnector.tsx` (if custom form needed)

- [ ] Create form component if JSM needs a different UI than regular Jira
- [ ] Otherwise, can reuse existing Jira form component with appropriate field labels

### Phase 3: Comprehensive Testing Strategy

**THIS IS A COMPREHENSIVE TESTING PHASE - TEST EVERYTHING!!!**

This phase covers ALL types of testing: Unit, Integration, E2E, Manual, and Exploratory testing. Every aspect of the connector must be thoroughly tested before production deployment.

**Testing Philosophy**: 
- ✅ Test happy paths
- ✅ Test error paths
- ✅ Test edge cases
- ✅ Test security
- ✅ Test performance
- ✅ Test under failure conditions
- ✅ Test integration points
- ✅ Test user workflows

**Quality Standards**:
- Unit test coverage ≥ 90%
- All critical paths have integration tests
- All user workflows have E2E tests
- All UI features manually tested
- Edge cases explored through exploratory testing

---

## 3.1 UNIT TESTS

**Directory**: `backend/tests/unit/onyx/connectors/jira_service_management/`

### 3.1.1 Core Connector Tests
**File**: `test_jira_service_management_connector.py`

#### Initialization & Configuration Tests
- [ ] Test connector initialization with valid parameters
  - Valid `jira_base_url`
  - Valid `jsm_project_key`
  - Optional parameters (comment_email_blacklist, labels_to_skip, include_issue_types)
- [ ] Test connector initialization with missing required parameters
- [ ] Test connector initialization with invalid URL formats
- [ ] Test connector initialization with empty/invalid project key
- [ ] Test default values for optional parameters
- [ ] Test parameter validation logic

#### Credential Loading Tests
- [ ] Test `load_credentials()` with valid credentials dictionary
  - Valid email and API token
  - Valid scoped token
  - Valid OAuth token
- [ ] Test `load_credentials()` with missing credentials
- [ ] Test `load_credentials()` with invalid credential formats
- [ ] Test credential refresh/update handling
- [ ] Test credential validation
- [ ] Mock Jira client creation and verify it's stored correctly

#### JQL Query Generation Tests
**File**: `test_jql_generation.py`

- [ ] Test `_get_jql_query()` with only project key
  - Verify correct project filter: `project = "PROJECT_KEY"`
- [ ] Test `_get_jql_query()` with project key and time range
  - Verify time constraints are added correctly
  - Verify date formatting is correct (ISO format)
- [ ] Test `_get_jql_query()` with custom JQL query
  - Verify custom query is combined with time constraints
  - Verify proper parentheses handling
- [ ] Test `_get_jql_query()` with issue type filtering
  - Verify issue type filters are added: `issuetype IN ("Incident", "Service Request")`
- [ ] Test `_get_jql_query()` with multiple filters combined
- [ ] Test JQL query escaping for special characters in project key
- [ ] Test JQL query with reserved words in project key (quotes handling)
- [ ] Test timezone handling in date queries
- [ ] Test edge cases: empty time range, very large time range

#### Document Processing Tests
**File**: `test_document_processing.py`

- [ ] Test processing JSM issue to Document object
  - Verify all metadata fields are extracted
  - Verify document ID format (URL)
  - Verify semantic identifier format
  - Verify title format
- [ ] Test processing issue with description
  - Text description
  - ADF (Atlassian Document Format) description
  - Empty description
  - Very long description
- [ ] Test processing issue with comments
  - Single comment
  - Multiple comments
  - Comments with email blacklist filtering
  - Empty comments list
- [ ] Test metadata extraction:
  - Reporter information and email
  - Assignee information and email
  - Priority, status, resolution
  - Labels (including skip logic)
  - Created/updated dates
  - Due date
  - Issue type
  - Parent issue (for subtasks)
  - Project key and name
- [ ] Test label skip logic
  - Issue with labels to skip
  - Issue without labels to skip
  - Multiple skip labels
- [ ] Test ticket size limits
  - Ticket exceeding max size (should be skipped)
  - Ticket within size limit
  - Edge case: exactly at limit
- [ ] Test processing different JSM issue types:
  - Incident
  - Service Request
  - Problem
  - Change
  - Sub-tasks

#### Checkpoint Handling Tests
**File**: `test_checkpointing.py`

- [ ] Test `build_dummy_checkpoint()` returns correct checkpoint structure
- [ ] Test `validate_checkpoint_json()` with valid JSON
- [ ] Test `validate_checkpoint_json()` with invalid JSON (should raise exception)
- [ ] Test `load_from_checkpoint()` with empty checkpoint (initial run)
- [ ] Test `load_from_checkpoint()` with existing checkpoint
- [ ] Test checkpoint update logic
  - V3 API checkpoint updates (all_issue_ids, cursor, ids_done)
  - V2 API checkpoint updates (offset)
- [ ] Test checkpoint callback mechanism
- [ ] Test `update_checkpoint_for_next_run()` for both API versions
- [ ] Test checkpoint persistence across multiple runs
- [ ] Test checkpoint with pagination state
- [ ] Test checkpoint error recovery

#### Permission Sync Tests
**File**: `test_permission_sync.py`

- [ ] Test `load_from_checkpoint_with_perm_sync()` includes permission data
- [ ] Test `_get_project_permissions()` caching mechanism
- [ ] Test permission data structure
- [ ] Test permission sync for different project visibility settings
- [ ] Test permission sync for multiple projects
- [ ] Test permission cache invalidation
- [ ] Test `retrieve_all_slim_docs_perm_sync()` includes permissions

#### Slim Document Tests
**File**: `test_slim_connector.py`

- [ ] Test `retrieve_all_slim_docs_perm_sync()` returns slim documents
- [ ] Test slim document structure (id, external_access)
- [ ] Test slim document batching
- [ ] Test slim document retrieval with time range
- [ ] Test slim document retrieval without time range (all documents)
- [ ] Test callback mechanism for indexing heartbeat

#### Validation Tests
**File**: `test_validation.py`

- [ ] Test `validate_connector_settings()` with valid settings
- [ ] Test `validate_connector_settings()` with invalid project key
- [ ] Test `validate_connector_settings()` with non-existent project
- [ ] Test `validate_connector_settings()` with expired credentials (401)
- [ ] Test `validate_connector_settings()` with insufficient permissions (403)
- [ ] Test `validate_connector_settings()` with invalid custom JQL
- [ ] Test `validate_connector_settings()` with rate limit errors (429)
- [ ] Test error message formatting and user-friendliness

#### Error Handling Tests
**File**: `test_error_handling.py`

- [ ] Test `_handle_jira_search_error()` for HTTP 400 errors
- [ ] Test `_handle_jira_search_error()` for HTTP 401 errors
- [ ] Test `_handle_jira_search_error()` for HTTP 403 errors
- [ ] Test `_handle_jira_search_error()` for HTTP 404 errors
- [ ] Test `_handle_jira_search_error()` for HTTP 429 (rate limit) errors
- [ ] Test `_handle_jira_search_error()` for HTTP 500 errors
- [ ] Test `_handle_jira_connector_settings_error()` for all error types
- [ ] Test exception propagation
- [ ] Test graceful degradation on API errors
- [ ] Test retry logic (if implemented)

#### Utility Function Tests
**File**: `test_utils.py`

- [ ] Test project key quoting (`quoted_jira_project`)
  - [ ] Normal project keys
  - [ ] Project keys with spaces
  - [ ] Project keys with special characters
  - [ ] Reserved words as project keys
  - [ ] Empty project key
- [ ] Test URL building for issues
  - [ ] Standard Jira URLs
  - [ ] Custom domain URLs
  - [ ] URLs with different protocols (http vs https)
  - [ ] URLs with ports
  - [ ] URLs with path prefixes
- [ ] Test date parsing and conversion
  - [ ] ISO format dates
  - [ ] Different timezone formats
  - [ ] Invalid date formats
  - [ ] Null/None dates
  - [ ] Edge cases (leap years, etc.)
- [ ] Test ADF (Atlassian Document Format) parsing
  - [ ] Simple text nodes
  - [ ] Bold/italic formatting
  - [ ] Lists (ordered and unordered)
  - [ ] Links
  - [ ] Code blocks
  - [ ] Nested structures
  - [ ] Invalid ADF structures
  - [ ] Empty ADF documents
- [ ] Test comment extraction and filtering
  - [ ] Comments with authors
  - [ ] Comments without authors
  - [ ] Deleted comments
  - [ ] Comments with attachments
  - [ ] Very long comments
  - [ ] Comments with special characters
  - [ ] Comments with HTML/ADF content
- [ ] Test email blacklist filtering logic
  - [ ] Exact email matches
  - [ ] Email with case variations
  - [ ] Email with domain variations
  - [ ] Multiple emails in blacklist
  - [ ] Empty blacklist
  - [ ] Invalid email formats in blacklist

#### Mock and Fixture Tests
**File**: `conftest.py`

- [ ] Create comprehensive pytest fixtures:
  - Mock Jira client
  - Sample JSM issues (various types)
  - Sample project data
  - Sample permission data
  - Mock API responses
- [ ] Test fixtures with different Jira API versions (v2, v3)
- [ ] Test fixtures with different issue types

---

## 3.2 INTEGRATION TESTS

### 3.2.1 External Dependency Unit Tests
**Directory**: `backend/tests/external_dependency_unit/connectors/jira_service_management/`

#### Permission Sync Integration Tests
**File**: `test_jira_service_management_group_sync.py`

- [ ] Test group sync with real Jira API (with test credentials)
- [ ] Test permission retrieval for JSM projects
- [ ] Test permission structure matches expected format
- [ ] Test permission sync with multiple user roles
- [ ] Test permission sync with project-level permissions
- [ ] Test permission sync with issue-level permissions
- [ ] Test permission caching and invalidation

#### Document Sync Integration Tests
**File**: `test_jira_service_management_doc_sync.py`

- [ ] Test full document sync from real JSM project
- [ ] Test document sync with real Jira API calls
- [ ] Test document sync pagination with real API
- [ ] Test checkpoint persistence across real sync runs
- [ ] Test document sync performance with large projects
- [ ] Test concurrent document syncs
- [ ] Test document sync with rate limiting

#### API Integration Tests
**File**: `test_api_integration.py`

- [ ] Test Jira Cloud API (v3) integration
- [ ] Test Jira Server/Data Center API (v2) integration
- [ ] Test enhanced search API (v3 only)
- [ ] Test bulk fetch API (v3 only)
- [ ] Test search API (v2)
- [ ] Test API version detection
- [ ] Test API error handling with real responses
- [ ] Test rate limit handling with real API responses

### 3.2.2 Daily/Integration Tests
**Directory**: `backend/tests/daily/connectors/jira_service_management/`

#### Full Sync Integration Test
**File**: `test_jira_service_management_basic.py`

**Setup Requirements (document in test file):**
```python
"""
Test Requirements:
1. Access to a Jira instance with JSM enabled
2. Environment variables:
   - JIRA_BASE_URL: Base URL of Jira instance (e.g., https://yourcompany.atlassian.net)
   - JIRA_USER_EMAIL: Email for API authentication
   - JIRA_API_TOKEN: API token for authentication
   - JSM_PROJECT_KEY: Key of a JSM project to test with
3. The JSM project should have:
   - At least 10-20 test issues of various types
   - Issues with comments
   - Issues with different statuses
   - Issues with different priorities
"""
```

- [ ] Test full document loading from JSM project
  - Verify all issues are retrieved
  - Verify document structure is correct
  - Verify metadata is complete
  - Verify no documents are skipped incorrectly
- [ ] Test incremental sync (polling)
  - Create new issue in JSM project
  - Run polling sync
  - Verify new issue is retrieved
  - Update existing issue
  - Verify update is reflected
- [ ] Test permission sync end-to-end
  - Verify permissions are retrieved correctly
  - Verify permissions are attached to documents
  - Verify permission structure matches expected format
- [ ] Test slim document retrieval
  - Verify all slim documents are retrieved
  - Verify slim documents have correct IDs
  - Verify permissions are included
- [ ] Test checkpoint persistence
  - Run initial sync (creates checkpoint)
  - Run second sync (uses checkpoint)
  - Verify no duplicate documents
  - Verify all documents are still retrieved
- [ ] Test error recovery
  - Simulate API error mid-sync
  - Verify checkpoint is saved correctly
  - Verify next sync resumes from checkpoint
- [ ] Test large project handling
  - Test with project containing 100+ issues
  - Test with project containing 1000+ issues
  - Verify performance is acceptable
  - Verify memory usage is reasonable
- [ ] Test different JSM project configurations
  - Test with project containing only Incidents
  - Test with project containing only Service Requests
  - Test with project containing mixed issue types
  - Test with project with customer portal enabled
- [ ] Test time range filtering
  - Test sync with specific time range
  - Verify only issues in range are retrieved
  - Test edge cases: very small range, very large range

#### Regression Tests
**File**: `test_regression.py`

- [ ] Test compatibility with existing Jira connector
  - Verify both connectors can run simultaneously
  - Verify no shared state conflicts
  - Verify registry doesn't conflict
  - Verify both can sync same Jira instance
  - Verify credential handling doesn't conflict
  - Verify permission sync doesn't conflict
- [ ] Test backward compatibility
  - Test with old checkpoint format (if applicable)
  - Test migration path
  - Test with old connector configurations
- [ ] Test with different Jira versions
  - Jira Cloud latest
  - Jira Cloud previous version
  - Jira Data Center 8.x
  - Jira Data Center 9.x
  - Jira Server (if still supported)
- [ ] Test API changes and deprecations
  - Test with deprecated API endpoints
  - Test migration to new API versions
  - Test handling of API version mismatches

#### Performance Integration Tests
**File**: `test_performance.py`

- [ ] **Sync Performance Tests**
  - [ ] Measure sync time for 100 issues
  - [ ] Measure sync time for 1,000 issues
  - [ ] Measure sync time for 10,000 issues
  - [ ] Measure memory usage during sync
  - [ ] Measure CPU usage during sync
  - [ ] Measure network bandwidth usage
  - [ ] Identify performance bottlenecks
  - [ ] Test with rate limiting enabled
  
- [ ] **Pagination Performance**
  - [ ] Test pagination with large result sets
  - [ ] Measure time per page
  - [ ] Test checkpoint overhead
  - [ ] Test bulk fetch performance (v3)
  
- [ ] **Search Performance**
  - [ ] Measure search query time
  - [ ] Test with complex queries
  - [ ] Test with multiple concurrent searches
  - [ ] Test search with large document index
  
- [ ] **Memory Leak Tests**
  - [ ] Run multiple sync cycles
  - [ ] Monitor memory usage over time
  - [ ] Verify memory is released after sync
  - [ ] Test with very large projects

#### Concurrency Tests
**File**: `test_concurrency.py`

- [ ] Test multiple concurrent syncs
  - [ ] Same connector, different projects
  - [ ] Different connectors, same Jira instance
  - [ ] Verify no race conditions
  - [ ] Verify no deadlocks
  - [ ] Verify thread safety
  
- [ ] Test concurrent API calls
  - [ ] Multiple searches simultaneously
  - [ ] Multiple bulk fetches simultaneously
  - [ ] Verify rate limiting works correctly
  - [ ] Verify no API conflicts
  
- [ ] Test concurrent checkpoints
  - [ ] Multiple syncs updating checkpoints
  - [ ] Verify checkpoint consistency
  - [ ] Verify no checkpoint corruption

---

## 3.3 END-TO-END (E2E) TESTS

**Directory**: `backend/tests/e2e/connectors/jira_service_management/` (if directory exists)
**OR**: Manual E2E test procedures

### 3.3.1 Full Workflow E2E Tests
**File**: `test_e2e_workflow.py` OR **Manual Test Procedure**

#### E2E Test: Complete Connector Lifecycle
- [ ] **Setup Phase**
  - [ ] Create connector via Onyx UI
  - [ ] Verify connector appears in connector list
  - [ ] Verify connector configuration is saved
  - [ ] Verify credentials are stored securely
  
- [ ] **Initial Sync Phase**
  - [ ] Trigger initial sync manually
  - [ ] Monitor sync progress in UI
  - [ ] Verify sync completes successfully
  - [ ] Verify documents appear in search results
  - [ ] Verify document count matches JSM project issue count
  - [ ] Verify no duplicate documents
  
- [ ] **Search & Discovery Phase**
  - [ ] Search for specific JSM ticket by key
  - [ ] Search for ticket by summary text
  - [ ] Search for ticket by description content
  - [ ] Verify search results include correct metadata
  - [ ] Verify search results link to correct Jira URLs
  - [ ] Test filtering by metadata (status, priority, etc.)
  
- [ ] **Incremental Update Phase**
  - [ ] Create new issue in JSM project
  - [ ] Wait for automatic polling sync (or trigger manually)
  - [ ] Verify new issue appears in search results
  - [ ] Update existing issue in JSM project
  - [ ] Verify updated issue reflects changes in search
  - [ ] Delete issue in JSM project (if possible)
  - [ ] Verify deleted issue handling (depends on pruning logic)
  
- [ ] **Permission Sync Phase (if enabled)**
  - [ ] Verify permissions are synced correctly
  - [ ] Test document access control
  - [ ] Verify users only see documents they have access to
  - [ ] Test permission updates in JSM
  - [ ] Verify permission updates are reflected
  
- [ ] **Error Handling Phase**
  - [ ] Expire API token in JSM
  - [ ] Verify error is reported in UI
  - [ ] Update credentials
  - [ ] Verify sync resumes successfully
  - [ ] Test with invalid project key
  - [ ] Verify appropriate error message
  
- [ ] **Cleanup Phase**
  - [ ] Delete connector
  - [ ] Verify documents are removed (or marked as orphaned)
  - [ ] Verify no residual data remains

### 3.3.2 UI E2E Tests
**File**: Frontend E2E tests (if using Playwright/Cypress)

#### Connector Management E2E Tests
- [ ] **Test connector creation flow in UI**
  - [ ] Navigate to "Add Connector" page
  - [ ] Verify JSM connector appears in list
  - [ ] Select "Jira Service Management"
  - [ ] Verify form fields are displayed
  - [ ] Fill in configuration form with valid data
  - [ ] Test form validation (empty fields, invalid URLs)
  - [ ] Test optional fields (can be left empty)
  - [ ] Submit form
  - [ ] Verify loading state during submission
  - [ ] Verify success message
  - [ ] Verify connector appears in connector list
  
- [ ] **Test connector configuration editing**
  - [ ] Navigate to existing connector
  - [ ] Click "Edit" button
  - [ ] Modify configuration fields
  - [ ] Save changes
  - [ ] Verify changes are persisted
  - [ ] Test with invalid values (should show errors)
  
- [ ] **Test connector deletion**
  - [ ] Navigate to connector settings
  - [ ] Click "Delete" button
  - [ ] Verify confirmation dialog appears
  - [ ] Cancel deletion (verify nothing happens)
  - [ ] Confirm deletion
  - [ ] Verify connector is removed from list
  - [ ] Verify related data is cleaned up (or marked orphaned)
  
- [ ] **Test sync status display**
  - [ ] Verify "Not Synced" status for new connector
  - [ ] Trigger sync manually
  - [ ] Verify "Syncing" status appears
  - [ ] Verify progress indicators (if available)
  - [ ] Wait for sync to complete
  - [ ] Verify "Synced" status with timestamp
  - [ ] Verify sync statistics (document count, etc.)
  
- [ ] **Test error message display in UI**
  - [ ] Test with invalid credentials
  - [ ] Verify error message is displayed clearly
  - [ ] Test with invalid project key
  - [ ] Verify actionable error messages
  - [ ] Test with network errors
  - [ ] Verify retry mechanisms are available
  
- [ ] **Test connector list display**
  - [ ] Verify all connectors are displayed
  - [ ] Verify JSM connector has correct icon
  - [ ] Verify status indicators are correct
  - [ ] Test sorting/filtering (if available)
  - [ ] Test pagination (if many connectors)

#### Search & Discovery E2E Tests
- [ ] **Test search functionality**
  - [ ] Perform basic search query
  - [ ] Verify results include JSM documents
  - [ ] Click on search result
  - [ ] Verify document details are displayed
  - [ ] Verify link to Jira works
  - [ ] Test filtering by source (JSM only)
  
- [ ] **Test document display**
  - [ ] Verify document title matches Jira issue
  - [ ] Verify metadata is displayed correctly
  - [ ] Verify content preview is accurate
  - [ ] Verify citation information is correct
  - [ ] Test document navigation (if applicable)

#### User Workflow E2E Tests
- [ ] **Complete user journey: Setup to Search**
  - [ ] Create JSM connector
  - [ ] Configure credentials
  - [ ] Trigger initial sync
  - [ ] Wait for sync completion
  - [ ] Perform search query
  - [ ] Verify results
  - [ ] Access document details
  - [ ] Navigate to source Jira issue
  
- [ ] **Complete user journey: Troubleshooting**
  - [ ] Create connector with invalid config
  - [ ] See error message
  - [ ] Fix configuration
  - [ ] Retry sync
  - [ ] Verify successful sync

---

## 3.4 MANUAL TESTS

### 3.4.1 Manual Testing Checklist

#### Pre-Deployment Manual Tests

##### Setup & Configuration
- [ ] Manual test: Create new connector via UI
  - [ ] Fill all required fields
  - [ ] Test form validation (empty fields, invalid URLs)
  - [ ] Test optional field handling
  - [ ] Submit and verify success
- [ ] Manual test: Edit existing connector
  - [ ] Modify configuration
  - ] Verify changes are saved
  - [ ] Test with invalid values
- [ ] Manual test: Delete connector
  - [ ] Verify confirmation dialog
  - [ ] Verify connector is removed
  - [ ] Verify related data cleanup

##### Authentication & Credentials
- [ ] Manual test: Valid credentials
  - [ ] Create connector with valid email/token
  - [ ] Verify connection succeeds
  - [ ] Verify sync works
- [ ] Manual test: Invalid credentials
  - [ ] Test with wrong email
  - [ ] Test with wrong token
  - [ ] Test with expired token
  - [ ] Verify error messages are clear
- [ ] Manual test: Credential update
  - [ ] Update credentials for existing connector
  - [ ] Verify sync resumes with new credentials

##### Document Sync
- [ ] Manual test: Full initial sync
  - [ ] Trigger sync for JSM project with 50+ issues
  - [ ] Monitor sync progress
  - [ ] Verify all issues are synced
  - [ ] Check sync duration is reasonable
  - [ ] Verify no crashes or timeouts
- [ ] Manual test: Incremental sync
  - [ ] Add 5 new issues in JSM
  - [ ] Wait for/trigger sync
  - [ ] Verify only new issues are retrieved
  - [ ] Verify checkpoint is updated
- [ ] Manual test: Large project sync
  - [ ] Sync project with 1000+ issues
  - [ ] Monitor memory usage
  - [ ] Monitor sync duration
  - [ ] Verify all issues are synced
  - [ ] Check for rate limit issues

##### Search & Discovery
- [ ] Manual test: Basic search
  - [ ] Search for issue by key (e.g., "IT-123")
  - [ ] Verify result appears
  - [ ] Verify metadata is displayed
  - [ ] Verify link to Jira works
- [ ] Manual test: Content search
  - [ ] Search for text from issue description
  - [ ] Verify issue appears in results
  - [ ] Verify snippet/preview is accurate
- [ ] Manual test: Comment search
  - [ ] Search for text from issue comment
  - [ ] Verify issue appears
  - [ ] Verify comment content is searchable
- [ ] Manual test: Metadata search
  - [ ] Filter by status (e.g., "Open")
  - [ ] Filter by priority (e.g., "High")
  - [ ] Filter by issue type (e.g., "Incident")
  - [ ] Verify filtering works correctly

##### UI/UX Testing
- [ ] Manual test: Connector list display
  - [ ] Verify JSM connector appears in list
  - [ ] Verify icon displays correctly
  - [ ] Verify status indicators work
- [ ] Manual test: Sync status indicators
  - [ ] Verify "Syncing" status during sync
  - [ ] Verify "Success" status after sync
  - [ ] Verify "Error" status on failure
  - [ ] Verify last sync time is displayed
- [ ] Manual test: Error messages
  - [ ] Test various error scenarios
  - [ ] Verify error messages are user-friendly
  - [ ] Verify error messages include actionable information
- [ ] Manual test: Documentation links
  - [ ] Verify docs link works
  - [ ] Verify docs are accurate

##### Performance Testing
- [ ] Manual test: Sync performance
  - [ ] Measure sync time for 100 issues
  - [ ] Measure sync time for 1000 issues
  - [ ] Verify performance is acceptable
- [ ] Manual test: Search performance
  - [ ] Measure search response time
  - [ ] Test with complex queries
  - [ ] Verify search is fast enough
- [ ] Manual test: Memory usage
  - [ ] Monitor memory during large sync
  - [ ] Verify no memory leaks
  - [ ] Verify memory usage is reasonable

##### Browser Compatibility (if applicable)
- [ ] Manual test: Chrome
  - [ ] Latest version
  - [ ] Previous version
  - [ ] Mobile Chrome
- [ ] Manual test: Firefox
  - [ ] Latest version
  - [ ] Previous version
  - [ ] Mobile Firefox
- [ ] Manual test: Safari
  - [ ] Latest version
  - [ ] Previous version
  - [ ] iOS Safari
- [ ] Manual test: Edge
  - [ ] Latest version
  - [ ] Chromium-based Edge
- [ ] Manual test: Mobile browsers
  - [ ] iOS Safari
  - [ ] Android Chrome
  - [ ] Verify responsive design works
- [ ] Verify UI works correctly in all browsers
- [ ] Test keyboard navigation
- [ ] Test screen reader compatibility (accessibility)

##### Accessibility Testing
- [ ] Manual test: Keyboard navigation
  - [ ] Tab through all form fields
  - [ ] Navigate with arrow keys
  - [ ] Submit forms with Enter key
  - [ ] Escape dialogs with Esc key
- [ ] Manual test: Screen reader compatibility
  - [ ] Test with NVDA (Windows)
  - [ ] Test with JAWS (Windows)
  - [ ] Test with VoiceOver (macOS/iOS)
  - [ ] Verify all elements are labeled correctly
  - [ ] Verify error messages are announced
- [ ] Manual test: Visual accessibility
  - [ ] Test with high contrast mode
  - [ ] Test with zoom levels (200%, 300%)
  - [ ] Test with color blindness simulators
  - [ ] Verify text is readable at all sizes

### 3.4.2 User Acceptance Testing (UAT) Scenarios

#### Scenario 1: IT Support Team Setup
- [ ] As an IT admin, I want to connect Onyx to our JSM project
- [ ] I configure the connector with our JSM project key
- [ ] I verify all support tickets are searchable in Onyx
- [ ] I search for a recent incident and find it instantly

#### Scenario 2: Customer Support Team Search
- [ ] As a support agent, I want to search for similar tickets
- [ ] I search for keywords related to a customer issue
- [ ] I find relevant past tickets with solutions
- [ ] I can click through to view full ticket in Jira

#### Scenario 3: Manager Reporting
- [ ] As a manager, I want to analyze ticket trends
- [ ] I search for all high-priority incidents from last month
- [ ] I get comprehensive results with metadata
- [ ] I can filter by assignee, status, etc.

---

## 3.5 EXPLORATORY TESTS

### 3.5.1 Ad-Hoc Exploratory Testing

#### Test Session 1: Unexpected Input Handling
**Duration**: 1-2 hours
**Goal**: Find edge cases and unexpected behavior

- [ ] **Test extreme project names**
  - [ ] Project key with special characters
  - [ ] Project key with Unicode characters
  - [ ] Very long project key
  - [ ] Project key that looks like SQL injection attempt
  - [ ] Project key that looks like JQL injection attempt
  
- [ ] **Test malformed responses**
  - [ ] Simulate API returning unexpected JSON structure
  - [ ] Simulate API returning partial data
  - [ ] Simulate API returning corrupted data
  - [ ] Test handling of null values in API responses
  
- [ ] **Test concurrent operations**
  - [ ] Trigger multiple syncs simultaneously
  - [ ] Edit connector while sync is running
  - [ ] Delete connector while sync is running
  - [ ] Test with multiple JSM connectors configured

#### Test Session 2: Data Integrity
**Duration**: 1-2 hours
**Goal**: Verify data consistency and correctness

- [ ] **Compare Onyx documents with source Jira issues**
  - [ ] Randomly sample 20 synced documents
  - [ ] Verify title matches Jira issue summary
  - [ ] Verify description content matches
  - [ ] Verify metadata matches (status, priority, assignee, etc.)
  - [ ] Verify all comments are included
  - [ ] Verify links work correctly
  
- [ ] **Test data updates**
  - [ ] Update issue in Jira
  - [ ] Verify update appears in Onyx
  - [ ] Verify old version is replaced (not duplicated)
  - [ ] Test with multiple rapid updates
  
- [ ] **Test data deletion**
  - [ ] Delete issue in Jira (if possible)
  - [ ] Verify handling in Onyx (marked as deleted, removed, etc.)
  - [ ] Test with issues that were synced, then deleted

#### Test Session 3: Performance Under Load
**Duration**: 1-2 hours
**Goal**: Find performance bottlenecks

- [ ] **Stress test sync**
  - [ ] Sync project with 10,000+ issues
  - [ ] Monitor resource usage (CPU, memory, network)
  - [ ] Identify slow operations
  - [ ] Test with slow/unreliable network connection
  - [ ] Test with rate-limited API responses
  
- [ ] **Stress test search**
  - [ ] Perform 100 sequential searches
  - [ ] Perform concurrent searches
  - [ ] Test with complex search queries
  - [ ] Monitor query performance

#### Test Session 4: Security & Privacy
**Duration**: 1-2 hours
**Goal**: Verify security measures work correctly

- [ ] **Test credential security**
  - [ ] Verify credentials are not logged
  - [ ] Verify credentials are encrypted at rest
  - [ ] Test credential exposure in error messages
  - [ ] Test with various credential formats
  
- [ ] **Test data privacy**
  - [ ] Verify comment email blacklist works
  - [ ] Test with PII in issue descriptions
  - [ ] Verify permissions respect data access rules
  - [ ] Test with restricted visibility issues

#### Test Session 5: Integration Points
**Duration**: 1-2 hours
**Goal**: Verify integration with other Onyx features

- [ ] **Test with Onyx features**
  - [ ] Test document chunking works correctly
  - [ ] Test embedding generation for JSM documents
  - [ ] Test document re-indexing
  - [ ] Test document pruning
  - [ ] Test with personas/assistants
  - [ ] Test citation generation
  
- [ ] **Test with other connectors**
  - [ ] Verify JSM connector doesn't interfere with regular Jira connector
  - [ ] Test both connectors can run simultaneously
  - [ ] Test both connectors can sync same Jira instance (different projects)

#### Test Session 6: API Version Compatibility
**Duration**: 1-2 hours
**Goal**: Verify compatibility with different Jira API versions

- [ ] **Test Jira Cloud (v3 API)**
  - [ ] Test enhanced search functionality
  - [ ] Test bulk fetch functionality
  - [ ] Test checkpoint mechanism
  - [ ] Verify all v3-specific features work
  - [ ] Test nextPageToken handling
  - [ ] Test pageToken expiration (7 days)
  - [ ] Test bulk fetch with large issue lists
  
- [ ] **Test Jira Server/Data Center (v2 API)**
  - [ ] Test search API functionality
  - [ ] Test pagination
  - [ ] Test checkpoint mechanism
  - [ ] Verify v2 compatibility
  - [ ] Test offset-based pagination
  - [ ] Test maxResults limits

#### Test Session 7: Real-World User Scenarios
**Duration**: 2-3 hours
**Goal**: Test actual user workflows end-to-end

- [ ] **Scenario: New IT Support Team Setup**
  - [ ] Setup connector for new JSM project
  - [ ] Initial sync of 500+ existing tickets
  - [ ] Verify all tickets searchable
  - [ ] Test daily incremental syncs
  - [ ] Verify performance is acceptable
  
- [ ] **Scenario: High-Volume Customer Support**
  - [ ] Sync project with 10,000+ tickets
  - [ ] Test search performance
  - [ ] Test filtering by metadata
  - [ ] Verify search accuracy
  - [ ] Test concurrent searches
  
- [ ] **Scenario: Multiple JSM Projects**
  - [ ] Setup 3+ different JSM connectors
  - [ ] Sync all simultaneously
  - [ ] Verify no conflicts
  - [ ] Test searching across all projects
  - [ ] Verify project-specific filtering works
  
- [ ] **Scenario: Cross-Connector Integration**
  - [ ] JSM connector + Regular Jira connector
  - [ ] JSM connector + Confluence connector
  - [ ] Verify unified search works
  - [ ] Verify source filtering works
  - [ ] Test citation accuracy

#### Test Session 8: Internationalization & Localization
**Duration**: 1 hour
**Goal**: Test with international characters and locales

- [ ] **Test Unicode Support**
  - [ ] Project keys with non-ASCII characters
  - [ ] Issue summaries in different languages
  - [ ] Issue descriptions in different languages
  - [ ] Comments in different languages
  - [ ] Chinese, Japanese, Korean characters
  - [ ] Arabic, Hebrew (RTL) characters
  - [ ] Emoji in issue content
  
- [ ] **Test Timezone Handling**
  - [ ] Issues created in different timezones
  - [ ] Date filtering across timezones
  - [ ] Timezone conversion accuracy
  - [ ] Daylight saving time transitions
  
- [ ] **Test Locale-Specific Formats**
  - [ ] Date formats in different locales
  - [ ] Number formats
  - [ ] Currency formats (if applicable)

### 3.5.2 Chaos Engineering Tests

#### Chaos Test 1: Network Failures
- [ ] Simulate network timeout during sync
- [ ] Simulate network disconnection mid-sync
- [ ] Simulate slow network (high latency)
- [ ] Simulate packet loss
- [ ] Verify graceful handling and recovery

#### Chaos Test 2: API Failures
- [ ] Simulate API returning 500 errors
- [ ] Simulate API rate limiting
- [ ] Simulate API timeout
- [ ] Simulate API returning invalid responses
- [ ] Verify error handling and retry logic

#### Chaos Test 3: Resource Exhaustion
- [ ] Test with limited memory
- [ ] Test with limited CPU
- [ ] Test with limited disk space
- [ ] Test with limited network bandwidth
- [ ] Verify graceful degradation

### 3.5.3 Mutation Testing

- [ ] **Code mutation testing** (if tools available)
  - [ ] Run mutation testing on connector code
  - [ ] Verify test coverage kills mutants
  - [ ] Identify weak tests
  - [ ] Improve test quality based on results

---

## 3.6 TEST COVERAGE METRICS

### Target Coverage Goals

- [ ] **Unit Test Coverage**: ≥ 90% code coverage
- [ ] **Integration Test Coverage**: All critical paths covered
- [ ] **E2E Test Coverage**: All user workflows covered
- [ ] **Manual Test Coverage**: All UI features tested
- [ ] **Exploratory Test Coverage**: All edge cases explored

### Coverage Reports

- [ ] Generate unit test coverage report (pytest-cov)
- [ ] Generate integration test coverage report
- [ ] Document manual test execution results
- [ ] Document exploratory test findings
- [ ] Create test coverage dashboard/visualization

### Test Metrics Tracking

- [ ] Track test execution time
- [ ] Track test pass/fail rates
- [ ] Track test flakiness
- [ ] Track bug discovery rate
- [ ] Track test maintenance effort

---

## 3.7 TEST DATA MANAGEMENT

### Test Data Requirements

- [ ] **Create test JSM projects**
  - [ ] Project with various issue types
  - [ ] Project with large number of issues
  - [ ] Project with various configurations
  - [ ] Project with customer portal enabled
  
- [ ] **Create test issues**
  - [ ] Issues with different types (Incident, Request, etc.)
  - [ ] Issues with different statuses
  - [ ] Issues with different priorities
  - [ ] Issues with comments
  - [ ] Issues with attachments (if supported)
  - [ ] Issues with custom fields
  - [ ] Issues with linked issues
  
- [ ] **Test user accounts**
  - [ ] Admin user
  - [ ] Regular user with project access
  - [ ] User without project access
  - [ ] Service account for API access

### Test Data Cleanup

- [ ] Document test data cleanup procedures
- [ ] Create scripts to clean up test data
- [ ] Verify no test data leaks to production
- [ ] Verify test data doesn't interfere between test runs

---

## 3.8 TEST AUTOMATION - CI/CD Integration

- [ ] **Unit tests in CI**
  - [ ] Run unit tests on every PR
  - [ ] Fail PR if unit tests fail
  - [ ] Generate coverage reports
  
- [ ] **Integration tests in CI**
  - [ ] Run integration tests on PR (if possible)
  - [ ] Run integration tests on merge to main
  - [ ] Use test credentials/secrets management
  
- [ ] **E2E tests in CI/CD**
  - [ ] Run E2E tests in staging environment
  - [ ] Run E2E tests before production deployment
  - [ ] Use browser automation (Playwright/Cypress) for UI tests

### Test Execution Strategy

- [ ] **Pre-commit hooks**
  - [ ] Run fast unit tests before commit
  - [ ] Run linting
  
- [ ] **PR checks**
  - [ ] Run full unit test suite
  - [ ] Run integration tests (if time permits)
  
- [ ] **Nightly runs**
  - [ ] Run full test suite including daily tests
  - [ ] Run performance tests
  - [ ] Run chaos engineering tests
  
- [ ] **Release candidate testing**
  - [ ] Run all test types
  - [ ] Manual testing checklist
  - [ ] Exploratory testing sessions

---

## 3.9 TEST AUTOMATION TOOLING & SCRIPTS

### Required Testing Tools

- [ ] **Unit Testing Framework**
  - [ ] pytest (Python unit testing)
  - [ ] pytest-cov (coverage reporting)
  - [ ] pytest-mock (mocking)
  - [ ] pytest-asyncio (if async code)
  - [ ] pytest-xdist (parallel execution)
  
- [ ] **Integration Testing Tools**
  - [ ] pytest with real API connections
  - [ ] Test Jira instance setup
  - [ ] Test credentials management
  - [ ] Test data fixtures
  
- [ ] **E2E Testing Tools**
  - [ ] Playwright or Cypress (frontend E2E)
  - [ ] Selenium (if needed)
  - [ ] Test containers (if applicable)
  
- [ ] **Performance Testing Tools**
  - [ ] pytest-benchmark (performance benchmarking)
  - [ ] memory_profiler (memory profiling)
  - [ ] cProfile (performance profiling)
  - [ ] Locust or JMeter (load testing)
  
- [ ] **Test Quality Tools**
  - [ ] Coverage.py (code coverage)
  - [ ] mutation testing tools (if available)
  - [ ] Static analysis tools
  
- [ ] **CI/CD Integration**
  - [ ] GitHub Actions workflows
  - [ ] Test result reporting
  - [ ] Coverage reporting
  - [ ] Test artifacts storage

### Test Scripts to Create

- [ ] **Setup Scripts**
  - [ ] `scripts/setup_test_environment.sh` - Setup test environment
  - [ ] `scripts/create_test_jira_project.py` - Create test Jira project
  - [ ] `scripts/cleanup_test_data.py` - Cleanup test data
  
- [ ] **Test Execution Scripts**
  - [ ] `scripts/run_unit_tests.sh` - Run all unit tests
  - [ ] `scripts/run_integration_tests.sh` - Run integration tests
  - [ ] `scripts/run_e2e_tests.sh` - Run E2E tests
  - [ ] `scripts/run_all_tests.sh` - Run full test suite
  
- [ ] **Test Reporting Scripts**
  - [ ] `scripts/generate_test_report.py` - Generate test reports
  - [ ] `scripts/upload_coverage.py` - Upload coverage to service
  - [ ] `scripts/compare_test_results.py` - Compare test runs

### Test Data Management Scripts

- [ ] **Test Data Creation**
  - [ ] Script to create test JSM project
  - [ ] Script to populate test issues
  - [ ] Script to create test users
  - [ ] Script to setup test permissions
  
- [ ] **Test Data Cleanup**
  - [ ] Script to delete test project
  - [ ] Script to cleanup test issues
  - [ ] Script to reset test state
  
- [ ] **Test Data Validation**
  - [ ] Script to verify test data integrity
  - [ ] Script to compare test data with source

### Mocking & Fixtures

- [ ] **Create comprehensive mocks**
  - [ ] Mock Jira API responses
  - [ ] Mock error responses
  - [ ] Mock rate limit responses
  - [ ] Mock network failures
  
- [ ] **Create reusable fixtures**
  - [ ] Connector fixtures
  - [ ] Credential fixtures
  - [ ] Issue fixtures
  - [ ] Project fixtures
  - [ ] Permission fixtures

---

## 3.10 TEST DOCUMENTATION

### Test Documentation Requirements

- [ ] **Test Plan Document**
  - [ ] Document all test types
  - [ ] Document test objectives
  - [ ] Document test scope
  - [ ] Document test schedule
  
- [ ] **Test Case Documentation**
  - [ ] Document all test cases
  - [ ] Document test steps
  - [ ] Document expected results
  - [ ] Document test data requirements
  
- [ ] **Test Execution Reports**
  - [ ] Document test execution results
  - [ ] Document bugs found
  - [ ] Document test coverage metrics
  - [ ] Document test execution time
  
- [ ] **Test Setup Guides**
  - [ ] Document how to set up test environment
  - [ ] Document how to run tests
  - [ ] Document test data setup
  - [ ] Document troubleshooting guide

---

## 3.11 TEST MAINTENANCE

### Ongoing Test Maintenance

- [ ] **Regular test review**
  - [ ] Review and update tests monthly
  - [ ] Remove obsolete tests
  - [ ] Add tests for new bugs found
  - [ ] Refactor flaky tests
  
- [ ] **Test data maintenance**
  - [ ] Update test data as needed
  - [ ] Clean up old test data
  - [ ] Maintain test data freshness
  
- [ ] **Test tool maintenance**
  - [ ] Update test dependencies
  - [ ] Update test frameworks
  - [ ] Update test infrastructure

---

## 3.12 TEST EXECUTION MATRIX

### Test Coverage Matrix

| Test Category | Component | Test Type | Priority | Status |
|--------------|-----------|-----------|----------|--------|
| Unit Tests | Connector Initialization | Unit | P0 | ⬜ |
| Unit Tests | Credential Loading | Unit | P0 | ⬜ |
| Unit Tests | JQL Generation | Unit | P0 | ⬜ |
| Unit Tests | Document Processing | Unit | P0 | ⬜ |
| Unit Tests | Checkpoint Handling | Unit | P0 | ⬜ |
| Unit Tests | Permission Sync | Unit | P1 | ⬜ |
| Unit Tests | Error Handling | Unit | P0 | ⬜ |
| Integration Tests | API Integration | Integration | P0 | ⬜ |
| Integration Tests | Permission Sync | Integration | P1 | ⬜ |
| Integration Tests | Document Sync | Integration | P0 | ⬜ |
| Integration Tests | Performance | Integration | P1 | ⬜ |
| Integration Tests | Concurrency | Integration | P1 | ⬜ |
| E2E Tests | Connector Lifecycle | E2E | P0 | ⬜ |
| E2E Tests | Search Workflow | E2E | P0 | ⬜ |
| E2E Tests | UI Workflows | E2E | P1 | ⬜ |
| Manual Tests | Setup & Configuration | Manual | P0 | ⬜ |
| Manual Tests | Authentication | Manual | P0 | ⬜ |
| Manual Tests | Document Sync | Manual | P0 | ⬜ |
| Manual Tests | Search & Discovery | Manual | P0 | ⬜ |
| Manual Tests | Browser Compatibility | Manual | P1 | ⬜ |
| Manual Tests | Accessibility | Manual | P2 | ⬜ |
| Exploratory Tests | Edge Cases | Exploratory | P1 | ⬜ |
| Exploratory Tests | Security | Exploratory | P0 | ⬜ |
| Exploratory Tests | Performance | Exploratory | P1 | ⬜ |
| Exploratory Tests | Chaos Engineering | Exploratory | P2 | ⬜ |

**Priority Legend:**
- P0: Critical - Must pass before release
- P1: Important - Should pass before release
- P2: Nice to have - Can be addressed post-release

### Test Environment Matrix

| Test Type | Environment | Jira Version | Test Data | Status |
|-----------|-------------|--------------|-----------|--------|
| Unit Tests | Local | N/A (Mocked) | Synthetic | ⬜ |
| Integration Tests | Test Jira Instance | Cloud v3 | Test Project | ⬜ |
| Integration Tests | Test Jira Instance | Server v2 | Test Project | ⬜ |
| E2E Tests | Staging | Cloud v3 | Test Project | ⬜ |
| Manual Tests | Staging | Cloud v3 | Real Project | ⬜ |
| Performance Tests | Staging | Cloud v3 | Large Project | ⬜ |

### Test Result Tracking

- [ ] **Create test execution spreadsheet/tool**
  - [ ] Track all test cases
  - [ ] Record pass/fail status
  - [ ] Record execution time
  - [ ] Record environment details
  - [ ] Link to bug reports
  - [ ] Track retest status
  
- [ ] **Create test report template**
  - [ ] Executive summary
  - [ ] Test coverage metrics
  - [ ] Pass/fail statistics
  - [ ] Known issues
  - [ ] Recommendations
  
- [ ] **Test sign-off process**
  - [ ] Unit tests: Developer sign-off
  - [ ] Integration tests: Developer sign-off
  - [ ] E2E tests: QA sign-off
  - [ ] Manual tests: QA sign-off
  - [ ] Exploratory tests: QA sign-off
  - [ ] Final approval: Tech Lead/Manager

---

## Testing Checklist Summary

Before marking testing phase as complete:

### Unit Tests
- [ ] All unit tests written and passing
- [ ] Code coverage ≥ 90%
- [ ] All edge cases covered
- [ ] All error paths tested

### Integration Tests
- [ ] All integration tests written and passing
- [ ] Tests use real API (with test credentials)
- [ ] All critical paths covered
- [ ] Permission sync tested

### E2E Tests
- [ ] All user workflows tested
- [ ] UI tests automated (if applicable)
- [ ] Full lifecycle tested
- [ ] Error scenarios tested

### Manual Tests
- [ ] All manual test checklist items completed
- [ ] All user scenarios tested
- [ ] All browsers tested (if applicable)
- [ ] Performance validated

### Exploratory Tests
- [ ] Multiple exploratory sessions completed
- [ ] Edge cases explored
- [ ] Security tested
- [ ] Performance tested under load
- [ ] Chaos engineering tests completed

### Test Infrastructure
- [ ] Tests integrated into CI/CD
- [ ] Test documentation complete
- [ ] Test data management in place
- [ ] Coverage reports generated

### Phase 4: Documentation

#### 4.1 Update Documentation Repository
**Repository**: [onyx-dot-app/documentation](https://github.com/onyx-dot-app/documentation)

- [ ] Create new documentation page: `docs/connectors/official/jira-service-management.md`
- [ ] Include:
  - Overview of JSM connector
  - Prerequisites (Jira instance with JSM enabled, project key)
  - Credential setup instructions:
    - How to create API token in Jira
    - Required permissions (read access to JSM project)
  - Configuration guide:
    - Jira base URL
    - JSM project key
    - Optional settings (comment email blacklist, labels to skip, etc.)
  - Screenshots of:
    - Connector configuration form
    - Where to find project key in Jira
    - Where to create API token
  - Troubleshooting section:
    - Common errors and solutions
    - Permission issues
    - Project key not found errors

### Phase 5: Validation & Edge Cases

#### 5.1 Error Handling
- [ ] Test invalid JSM project key
- [ ] Test project key that doesn't exist
- [ ] Test project key for non-JSM project (should still work but may not have JSM features)
- [ ] Test expired credentials
- [ ] Test insufficient permissions
- [ ] Test rate limiting

#### 5.2 Edge Cases
- [ ] Large JSM projects (thousands of tickets)
- [ ] Empty JSM projects
- [ ] Projects with deleted tickets
- [ ] Projects with restricted visibility
- [ ] JSM projects with customer portal integration
- [ ] Handling of JSM-specific fields (SLA, customer information, etc.)

#### 5.3 Compatibility
- [ ] Test with Jira Cloud (most common for JSM)
- [ ] Test with Jira Data Center (if supported)
- [ ] Test with different JSM project configurations
- [ ] Verify compatibility with existing Jira connector (should not interfere)

## Implementation Considerations

### Code Reusability
- **Reuse existing Jira utilities**: The JSM connector should heavily leverage code from `backend/onyx/connectors/jira/`:
  - `utils.py`: Jira client building, URL building, ADF parsing, etc.
  - `access.py`: Permission handling
  - `connector.py`: Checkpoint handling, JQL search logic
  
- **Consider inheritance vs composition**: 
  - Option A: Create `JiraServiceManagementConnector` as a subclass of `JiraConnector`
  - Option B: Create a separate connector that uses shared utilities
  - **Recommendation**: Option B (composition) is preferred to avoid tight coupling and allow independent evolution

### JSM-Specific Features (Future Enhancements)
- Customer portal information
- SLA tracking data
- Customer-facing request types
- JSM-specific workflows
- Asset management integration

### Performance Considerations
- JSM projects can be very large (especially for enterprise customers)
- Use the same checkpointing strategy as Jira connector
- Consider pagination and rate limiting
- Support both v2 and v3 APIs (like Jira connector)

### Security Considerations
- JSM projects may contain sensitive customer information
- Ensure proper permission checking
- Respect email blacklist for comments
- Handle PII appropriately

## Testing Checklist

### Pre-PR Testing Checklist

Before submitting PR, verify ALL of the following:

#### Unit Tests ✅
- [ ] All unit tests written and passing (≥90% coverage)
- [ ] Test files organized correctly
- [ ] All fixtures and mocks created
- [ ] All edge cases covered
- [ ] All error paths tested

#### Integration Tests ✅
- [ ] All integration tests written and passing
- [ ] Tests use real Jira API (with test credentials)
- [ ] Permission sync integration tests passing
- [ ] Document sync integration tests passing
- [ ] API version compatibility tested

#### Daily/External Dependency Tests ✅
- [ ] Daily tests pass with real JSM project
- [ ] Test setup instructions documented
- [ ] All test scenarios covered
- [ ] Tests are repeatable and stable

#### E2E Tests ✅
- [ ] Complete connector lifecycle tested
- [ ] UI workflows tested (if applicable)
- [ ] All user scenarios validated
- [ ] Error recovery tested

#### Manual Tests ✅
- [ ] Connector can be created via UI
- [ ] Connector configuration form works correctly
- [ ] Connector successfully syncs documents
- [ ] Documents appear in search results
- [ ] Search functionality works correctly
- [ ] Permission sync works (if applicable)
- [ ] Slim connector works for pruning
- [ ] Error messages are user-friendly
- [ ] UI displays correctly in all browsers
- [ ] Performance is acceptable

#### Exploratory Tests ✅
- [ ] Edge cases explored and handled
- [ ] Security testing completed
- [ ] Performance under load validated
- [ ] Chaos engineering tests completed
- [ ] Integration points verified

#### Code Quality ✅
- [ ] Code follows Onyx style guidelines
- [ ] No linting errors
- [ ] Code is well-documented
- [ ] Type hints are correct
- [ ] Error handling is comprehensive

#### Documentation ✅
- [ ] Code comments are complete
- [ ] Test documentation is complete
- [ ] User documentation is complete
- [ ] Setup instructions are clear
- [ ] Troubleshooting guide is included

#### CI/CD ✅
- [ ] All tests pass in CI
- [ ] Coverage reports generated
- [ ] No flaky tests
- [ ] Test execution time is reasonable

### Sign-Off Checklist

- [ ] **Developer Sign-Off**: All code complete and tested
- [ ] **QA Sign-Off**: All test scenarios validated (if applicable)
- [ ] **Code Review**: At least one reviewer approval
- [ ] **Documentation Review**: Documentation verified complete
- [ ] **Security Review**: Security considerations validated (if applicable)

## Dependencies

- Existing dependencies (already in requirements):
  - `jira` Python library
  - Existing Jira connector utilities

- No new dependencies should be required (reuses existing Jira infrastructure)

## Timeline Estimate

- **Phase 1 (Backend Core)**: 2-3 days
- **Phase 2 (Frontend)**: 1 day
- **Phase 3 (Testing - COMPREHENSIVE)**: 8-12 days
  - Unit Tests: 3-4 days
  - Integration Tests: 2-3 days
  - E2E Tests: 1-2 days
  - Manual Tests: 1-2 days
  - Exploratory Tests: 1-2 days
- **Phase 4 (Documentation)**: 1-2 days
- **Phase 5 (Validation)**: 1-2 days

**Total**: ~13-20 days

**Note**: The comprehensive testing phase significantly extends the timeline but ensures production-ready quality. Consider parallelizing testing activities where possible (e.g., unit tests can be written alongside implementation, manual tests can run in parallel with automation).

## Success Criteria

1. ✅ Connector can be configured via Onyx UI
2. ✅ Connector successfully pulls all tickets from a specified JSM project
3. ✅ Documents are properly indexed and searchable
4. ✅ Permission sync works correctly (if enabled)
5. ✅ Connector handles large projects efficiently
6. ✅ Comprehensive test coverage
7. ✅ Documentation is complete and accurate
8. ✅ No conflicts with existing Jira connector

## Open Questions / Decisions Needed

1. **Should we filter by JSM-specific issue types by default?**
   - Recommendation: No, allow all issue types but make it configurable

2. **Should we extract JSM-specific metadata (SLA, customer portal, etc.)?**
   - Recommendation: Start with basic implementation, add JSM-specific metadata in future PR

3. **Should the connector validate that the project is actually a JSM project?**
   - Recommendation: Yes, validate project type if possible via API

4. **Naming convention**: Use `jira_service_management` or `jira_sm` or `jsm`?
   - Recommendation: `jira_service_management` for clarity

5. **Icon**: Reuse Jira icon or create JSM-specific icon?
   - Recommendation: Reuse Jira icon initially, can add JSM-specific icon later

## References

- [Issue #2281](https://github.com/onyx-dot-app/onyx/issues/2281)
- [Connector Creation README](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/README.md)
- [Existing Jira Connector](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/jira/connector.py)
- [Jira REST API Documentation](https://developer.atlassian.com/cloud/jira/platform/rest/v3/)
- [Jira Service Management API](https://developer.atlassian.com/cloud/jira/service-management/rest/)

## Notes

- The existing Jira connector is well-tested and production-ready. This implementation should follow the same patterns and quality standards.
- JSM uses the same API as regular Jira, so most of the complexity is already handled by the existing Jira connector code.
- Consider this as a "specialized Jira connector" rather than a completely new connector - maximum code reuse is key.
