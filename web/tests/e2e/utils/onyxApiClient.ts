import { Page, expect, APIResponse } from "@playwright/test";

/**
 * API Client for Onyx backend operations in E2E tests.
 *
 * Provides a type-safe, abstracted interface for interacting with the Onyx backend API.
 * All methods handle authentication via the Playwright page context and include automatic
 * error handling, logging, and polling for asynchronous operations.
 *
 * **Available Endpoints:**
 *
 * **Connectors:**
 * - `createFileConnector(name)` - Creates a file connector with mock credentials
 * - `deleteCCPair(ccPairId)` - Deletes a connector-credential pair (with polling until complete)
 *
 * **Document Sets:**
 * - `createDocumentSet(name, ccPairIds)` - Creates a document set from connector pairs
 * - `deleteDocumentSet(id)` - Deletes a document set (with polling until complete)
 *
 * **Usage Example:**
 * ```typescript
 * const client = new OnyxApiClient(page);
 * const { ccPairId } = await client.createFileConnector("Test Connector");
 * const docSetId = await client.createDocumentSet("Test Set", [ccPairId]);
 * await client.deleteDocumentSet(docSetId);
 * await client.deleteCCPair(ccPairId);
 * ```
 *
 * @param page - Playwright Page instance with authenticated session
 */
export class OnyxApiClient {
  private baseUrl = "http://localhost:3000/api";

  constructor(private page: Page) {}

  /**
   * Generic GET request to the API.
   *
   * @param endpoint - API endpoint path (e.g., "/manage/document-set/123")
   * @returns The API response
   */
  private async get(endpoint: string): Promise<APIResponse> {
    return await this.page.request.get(`${this.baseUrl}${endpoint}`);
  }

  /**
   * Generic POST request to the API.
   *
   * @param endpoint - API endpoint path (e.g., "/manage/admin/document-set")
   * @param data - Optional request body data
   * @returns The API response
   */
  private async post(endpoint: string, data?: any): Promise<APIResponse> {
    return await this.page.request.post(`${this.baseUrl}${endpoint}`, {
      data,
    });
  }

  /**
   * Generic DELETE request to the API.
   *
   * @param endpoint - API endpoint path (e.g., "/manage/admin/document-set/123")
   * @returns The API response
   */
  private async delete(endpoint: string): Promise<APIResponse> {
    return await this.page.request.delete(`${this.baseUrl}${endpoint}`);
  }

  /**
   * Handle API response - parse JSON and handle errors.
   *
   * @param response - The API response to handle
   * @param errorMessage - Error message prefix to use if request failed
   * @returns Parsed JSON response data
   * @throws Error if the response is not ok
   */
  private async handleResponse<T>(
    response: APIResponse,
    errorMessage: string
  ): Promise<T> {
    if (!response.ok()) {
      const errorText = await response.text();
      throw new Error(`${errorMessage}: ${response.status()} - ${errorText}`);
    }
    return await response.json();
  }

  /**
   * Handle API response with logging on error (non-throwing).
   * Used for cleanup operations where we want to log errors but not fail the test.
   *
   * @param response - The API response to handle
   * @param errorMessage - Error message prefix to use if request failed
   * @returns true if response was ok, false otherwise
   */
  private async handleResponseSoft(
    response: APIResponse,
    errorMessage: string
  ): Promise<boolean> {
    if (!response.ok()) {
      const errorText = await response.text();
      console.error(
        `[OnyxApiClient] ${errorMessage}: ${response.status()} - ${errorText}`
      );
      return false;
    }
    return true;
  }

  /**
   * Wait for a resource to be deleted by polling until 404.
   * Uses Playwright's expect.poll() with automatic retry and exponential backoff.
   * We poll here because the deletion endpoint is asynchronous (kicks off a celery task)
   * and we want to wait for it to complete.
   *
   * @param endpoint - API endpoint to poll (e.g., "/manage/document-set/123")
   * @param resourceType - Human-readable resource type for error messages (e.g., "Document set")
   * @param resourceId - The resource ID for error messages
   * @param timeout - Maximum time to wait in milliseconds (default: 30000)
   * @returns Promise that resolves when resource returns 404, or rejects on timeout
   */
  private async waitForDeletion(
    endpoint: string,
    resourceType: string,
    resourceId: number | string,
    timeout: number = 30000
  ): Promise<void> {
    await expect
      .poll(
        async () => {
          const checkResponse = await this.get(endpoint);
          return checkResponse.status();
        },
        {
          message: `${resourceType} ${resourceId} was not deleted`,
          timeout,
        }
      )
      .toBe(404);
  }

  /**
   * Log an action with consistent formatting.
   *
   * @param message - The message to log (will be prefixed with "[OnyxApiClient]")
   */
  private log(message: string): void {
    console.log(`[OnyxApiClient] ${message}`);
  }

  /**
   * Creates a simple file connector with mock credentials.
   * This enables the Knowledge toggle in assistant creation.
   *
   * @param connectorName - Name for the connector (defaults to "Test File Connector")
   * @returns The connector-credential pair ID (ccPairId)
   * @throws Error if the connector creation fails
   */
  async createFileConnector(
    connectorName: string = "Test File Connector"
  ): Promise<number> {
    const response = await this.post(
      "/manage/admin/connector-with-mock-credential",
      {
        name: connectorName,
        source: "file",
        input_type: "load_state",
        connector_specific_config: {
          file_locations: [],
        },
        refresh_freq: null,
        prune_freq: null,
        indexing_start: null,
        access_type: "public",
        groups: [],
      }
    );

    const responseData = await this.handleResponse<{ data: number }>(
      response,
      "Failed to create connector"
    );

    const ccPairId = responseData.data;
    this.log(
      `Created file connector: ${connectorName} (CC Pair ID: ${ccPairId})`
    );

    return ccPairId;
  }

  /**
   * Creates a document set from connector-credential pairs.
   *
   * @param documentSetName - Name for the document set
   * @param ccPairIds - Array of connector-credential pair IDs to include in the set
   * @returns The document set ID
   * @throws Error if the document set creation fails
   */
  async createDocumentSet(
    documentSetName: string,
    ccPairIds: number[]
  ): Promise<number> {
    const response = await this.post("/manage/admin/document-set", {
      name: documentSetName,
      description: `Test document set: ${documentSetName}`,
      cc_pair_ids: ccPairIds,
      is_public: true,
      users: [],
      groups: [],
      federated_connectors: [],
    });

    const documentSetId = await this.handleResponse<number>(
      response,
      "Failed to create document set"
    );

    this.log(`Created document set: ${documentSetName} (ID: ${documentSetId})`);
    return documentSetId;
  }

  /**
   * Deletes a document set and waits for deletion to complete.
   * Uses polling to verify the deletion was successful (waits for 404 response).
   *
   * @param documentSetId - The document set ID to delete
   * @returns Promise that resolves when deletion is confirmed, or rejects on timeout
   */
  async deleteDocumentSet(documentSetId: number): Promise<void> {
    const response = await this.delete(
      `/manage/admin/document-set/${documentSetId}`
    );

    if (
      !(await this.handleResponseSoft(
        response,
        `Failed to delete document set ${documentSetId}`
      ))
    ) {
      return;
    }

    this.log(`Initiated deletion for document set: ${documentSetId}`);
    await this.waitForDeletion(
      `/manage/document-set/${documentSetId}`,
      "Document set",
      documentSetId
    );
    this.log(`Document set ${documentSetId} deletion confirmed`);
  }

  /**
   * Deletes a connector-credential pair and waits for deletion to complete.
   * Fetches the CC pair details to get connector/credential IDs, then initiates deletion
   * and polls until the deletion is confirmed (waits for 404 response).
   *
   * @param ccPairId - The connector-credential pair ID to delete
   * @returns Promise that resolves when deletion is confirmed, or rejects on timeout
   */
  async deleteCCPair(ccPairId: number): Promise<void> {
    // Get CC pair details to extract connector_id and credential_id
    const getResponse = await this.get(`/manage/admin/cc-pair/${ccPairId}`);

    if (
      !(await this.handleResponseSoft(
        getResponse,
        `Failed to get CC pair ${ccPairId} details`
      ))
    ) {
      return;
    }

    const ccPairInfo = await getResponse.json();
    const {
      connector: { id: connectorId },
      credential: { id: credentialId },
    } = ccPairInfo;

    // Delete using the deletion-attempt endpoint
    const deleteResponse = await this.post("/manage/admin/deletion-attempt", {
      connector_id: connectorId,
      credential_id: credentialId,
    });

    if (
      !(await this.handleResponseSoft(
        deleteResponse,
        `Failed to delete CC pair ${ccPairId}`
      ))
    ) {
      return;
    }

    this.log(
      `Initiated deletion for CC pair: ${ccPairId} (connector: ${connectorId}, credential: ${credentialId})`
    );
    await this.waitForDeletion(
      `/manage/admin/cc-pair/${ccPairId}`,
      "CC pair",
      ccPairId
    );
    this.log(`CC pair ${ccPairId} deletion confirmed`);
  }
}
