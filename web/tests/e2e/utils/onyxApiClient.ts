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
 * **LLM Providers:**
 * - `createRestrictedProvider(name, groupId)` - Creates a restricted LLM provider assigned to a group
 * - `deleteProvider(id)` - Deletes an LLM provider
 *
 * **User Groups:**
 * - `createUserGroup(name)` - Creates a user group
 * - `deleteUserGroup(id)` - Deletes a user group
 *
 * **Tool Providers:**
 * - `createWebSearchProvider(type, name)` - Creates and activates a web search provider
 * - `deleteWebSearchProvider(id)` - Deletes a web search provider
 * - `createImageGenerationConfig(id, model, provider, isDefault)` - Creates an image generation config (enables image gen tool)
 * - `deleteImageGenerationConfig(id)` - Deletes an image generation config
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
  private baseUrl = `${process.env.BASE_URL || "http://localhost:3000"}/api`;

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
   * Generic PUT request to the API.
   *
   * @param endpoint - API endpoint path (e.g., "/manage/admin/cc-pair/123/status")
   * @param data - Optional request body data
   * @returns The API response
   */
  private async put(endpoint: string, data?: any): Promise<APIResponse> {
    return await this.page.request.put(`${this.baseUrl}${endpoint}`, {
      data,
    });
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

    // Pause the connector immediately to prevent indexing during tests
    await this.pauseConnector(ccPairId);

    return ccPairId;
  }

  /**
   * Pauses a connector-credential pair to prevent indexing.
   *
   * @param ccPairId - The connector-credential pair ID to pause
   * @throws Error if the pause operation fails
   */
  async pauseConnector(ccPairId: number): Promise<void> {
    const response = await this.put(
      `/manage/admin/cc-pair/${ccPairId}/status`,
      {
        status: "PAUSED",
      }
    );

    await this.handleResponse(response, "Failed to pause connector");
    this.log(`Paused connector CC Pair ID: ${ccPairId}`);
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

  /**
   * Creates a restricted LLM provider assigned to a specific user group.
   *
   * @param providerName - Name for the provider
   * @param groupId - The user group ID that should have access to this provider
   * @returns The provider ID
   * @throws Error if the provider creation fails
   */
  async createRestrictedProvider(
    providerName: string,
    groupId: number
  ): Promise<number> {
    const response = await this.page.request.put(
      `${this.baseUrl}/admin/llm/provider?is_creation=true`,
      {
        data: {
          name: providerName,
          provider: "openai",
          api_key: "test-key",
          default_model_name: "gpt-4o",
          is_public: false,
          groups: [groupId],
          personas: [],
        },
      }
    );

    const responseData = await this.handleResponse<{ id: number }>(
      response,
      "Failed to create restricted provider"
    );

    this.log(
      `Created restricted LLM provider: ${providerName} (ID: ${responseData.id}, Group: ${groupId})`
    );
    return responseData.id;
  }

  /**
   * Deletes an LLM provider.
   *
   * @param providerId - The provider ID to delete
   */
  async deleteProvider(providerId: number): Promise<void> {
    const response = await this.delete(`/admin/llm/provider/${providerId}`);

    await this.handleResponseSoft(
      response,
      `Failed to delete provider ${providerId}`
    );

    this.log(`Deleted LLM provider: ${providerId}`);
  }

  /**
   * Creates a user group.
   *
   * @param groupName - Name for the user group
   * @returns The user group ID
   * @throws Error if the user group creation fails
   */
  async createUserGroup(
    groupName: string,
    userIds: string[] = []
  ): Promise<number> {
    const response = await this.post("/manage/admin/user-group", {
      name: groupName,
      user_ids: userIds,
      cc_pair_ids: [],
    });

    const responseData = await this.handleResponse<{ id: number }>(
      response,
      "Failed to create user group"
    );

    this.log(`Created user group: ${groupName} (ID: ${responseData.id})`);
    return responseData.id;
  }

  /**
   * Deletes a user group.
   *
   * @param groupId - The user group ID to delete
   */
  async deleteUserGroup(groupId: number): Promise<void> {
    const response = await this.delete(`/manage/admin/user-group/${groupId}`);

    await this.handleResponseSoft(
      response,
      `Failed to delete user group ${groupId}`
    );

    this.log(`Deleted user group: ${groupId}`);
  }

  async setUserRole(
    email: string,
    role: "admin" | "curator" | "global_curator" | "basic",
    explicitOverride = false
  ): Promise<void> {
    const response = await this.page.request.patch(
      `${this.baseUrl}/manage/set-user-role`,
      {
        data: {
          user_email: email,
          new_role: role,
          explicit_override: explicitOverride,
        },
      }
    );
    await this.handleResponse(response, `Failed to set user role for ${email}`);
    this.log(`Updated role for ${email} to ${role}`);
  }

  async deleteMcpServer(serverId: number): Promise<boolean> {
    const response = await this.page.request.delete(
      `${this.baseUrl}/admin/mcp/server/${serverId}`
    );
    const success = await this.handleResponseSoft(
      response,
      `Failed to delete MCP server ${serverId}`
    );
    if (success) {
      this.log(`Deleted MCP server ${serverId}`);
    }
    return success;
  }

  async deleteAssistant(assistantId: number): Promise<boolean> {
    const response = await this.page.request.delete(
      `${this.baseUrl}/persona/${assistantId}`
    );
    const success = await this.handleResponseSoft(
      response,
      `Failed to delete assistant ${assistantId}`
    );
    if (success) {
      this.log(`Deleted assistant ${assistantId}`);
    }
    return success;
  }

  async listMcpServers(): Promise<any[]> {
    const response = await this.get(`/admin/mcp/servers`);
    const data = await this.handleResponse<{ mcp_servers: any[] }>(
      response,
      "Failed to list MCP servers"
    );
    return data.mcp_servers;
  }

  async listAssistants(options?: {
    includeDeleted?: boolean;
    getEditable?: boolean;
  }): Promise<any[]> {
    const params = new URLSearchParams();
    if (options?.includeDeleted) {
      params.set("include_deleted", "true");
    }
    if (options?.getEditable ?? true) {
      params.set("get_editable", "true");
    }
    const query = params.toString();
    const response = await this.get(
      `/admin/persona${query ? `?${query}` : ""}`
    );
    return await this.handleResponse<any[]>(
      response,
      "Failed to list assistants"
    );
  }

  async findAssistantByName(
    name: string,
    options?: { includeDeleted?: boolean; getEditable?: boolean }
  ): Promise<any | null> {
    const assistants = await this.listAssistants(options);
    return assistants.find((assistant) => assistant.name === name) ?? null;
  }

  async registerUser(email: string, password: string): Promise<{ id: string }> {
    const response = await this.page.request.post(
      `${this.baseUrl}/auth/register`,
      {
        data: {
          email,
          username: email,
          password,
        },
      }
    );
    const data = await this.handleResponse<{ id: string }>(
      response,
      `Failed to register user ${email}`
    );
    return data;
  }

  async getUserByEmail(email: string): Promise<{
    id: string;
    email: string;
    role: string;
  } | null> {
    const response = await this.page.request.get(
      `${this.baseUrl}/manage/users/accepted`,
      {
        params: {
          q: email,
          page_size: 1,
        },
      }
    );
    const data = await this.handleResponse<{ items: any[] }>(
      response,
      `Failed to fetch user ${email}`
    );
    const [user] = data.items;
    return user
      ? {
          id: user.id,
          email: user.email,
          role: user.role,
        }
      : null;
  }

  async setCuratorStatus(
    userGroupId: string,
    userId: string,
    isCurator: boolean = true
  ): Promise<void> {
    const response = await this.page.request.post(
      `${this.baseUrl}/manage/admin/user-group/${userGroupId}/set-curator`,
      {
        data: {
          user_id: userId,
          is_curator: isCurator,
        },
      }
    );
    await this.handleResponse(
      response,
      `Failed to update curator status for ${userId}`
    );
  }

  /**
   * Create and activate a web search provider for testing.
   * Uses a dummy API key that won't actually work, but allows the tool to be available.
   *
   * @param providerType - Type of provider: "exa", "serper", "google_pse", "searxng"
   * @param name - Optional name for the provider (defaults to "Test Provider")
   * @returns The created provider ID
   */
  async createWebSearchProvider(
    providerType: "exa" | "serper" | "google_pse" | "searxng" = "exa",
    name: string = "Test Provider"
  ): Promise<number> {
    const config: Record<string, string> = {};
    if (providerType === "google_pse") {
      config.search_engine_id = "test-engine-id";
    }
    if (providerType === "searxng") {
      config.searxng_base_url = "https://test-searxng.example.com";
    }

    const response = await this.post("/admin/web-search/search-providers", {
      name,
      provider_type: providerType,
      api_key: "test-api-key-12345",
      api_key_changed: true,
      config: Object.keys(config).length > 0 ? config : undefined,
      activate: true,
    });

    const data = await this.handleResponse<{ id: number }>(
      response,
      `Failed to create web search provider ${providerType}`
    );
    return data.id;
  }

  /**
   * Delete a web search provider.
   *
   * @param providerId - ID of the provider to delete
   */
  async deleteWebSearchProvider(providerId: number): Promise<void> {
    const response = await this.delete(
      `/admin/web-search/search-providers/${providerId}`
    );
    if (!response.ok()) {
      const errorText = await response.text();
      console.warn(
        `Failed to delete web search provider ${providerId}: ${response.status()} - ${errorText}`
      );
    }
  }

  /**
   * Creates an image generation configuration for testing.
   * This enables the image generation tool in assistants.
   *
   * API: POST /api/admin/image-generation/config
   * Schema (ImageGenerationConfigCreate):
   *   - image_provider_id: string (required) - unique key
   *   - model_name: string (required) - e.g., "dall-e-3"
   *   - provider: string - e.g., "openai"
   *   - api_key: string
   *   - is_default: boolean
   *
   * @param imageProviderId - Unique identifier for the image generation config
   * @param modelName - Model name (defaults to "dall-e-3")
   * @param provider - Provider name (defaults to "openai")
   * @param isDefault - Whether this should be the default config (defaults to true)
   * @returns The image_provider_id
   */
  async createImageGenerationConfig(
    imageProviderId: string,
    modelName: string = "dall-e-3",
    provider: string = "openai",
    isDefault: boolean = true
  ): Promise<string> {
    const response = await this.post("/admin/image-generation/config", {
      image_provider_id: imageProviderId,
      model_name: modelName,
      provider: provider,
      api_key: "test-api-key", // Dummy key - enables tool visibility
      is_default: isDefault,
    });

    await this.handleResponse(
      response,
      "Failed to create image generation config"
    );

    this.log(`Created image generation config: ${imageProviderId}`);
    return imageProviderId;
  }

  /**
   * Deletes an image generation configuration.
   *
   * @param imageProviderId - The image_provider_id to delete
   */
  async deleteImageGenerationConfig(imageProviderId: string): Promise<void> {
    const response = await this.delete(
      `/admin/image-generation/config/${imageProviderId}`
    );

    await this.handleResponseSoft(
      response,
      `Failed to delete image generation config ${imageProviderId}`
    );

    this.log(`Deleted image generation config: ${imageProviderId}`);
  }
}
