import { ValidSources } from "@/lib/types";
import {
  fetchHierarchyNodeDocuments,
  fetchHierarchyNodes,
} from "@/lib/hierarchy/svc";

describe("hierarchy service", () => {
  const mockFetch = jest.fn();

  beforeEach(() => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ nodes: [] }),
    });
    global.fetch = mockFetch as unknown as typeof fetch;
  });

  afterEach(() => {
    mockFetch.mockReset();
  });

  it("uses the generic hierarchy endpoint without LTI context", async () => {
    await fetchHierarchyNodes(ValidSources.GoogleDrive);

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/hierarchy-nodes?source=google_drive"
    );
  });

  it("uses the LTI-scoped hierarchy endpoint with LTI context", async () => {
    await fetchHierarchyNodes(ValidSources.GoogleDrive, "course A/B");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/auth/lti/course/course%20A%2FB/knowledge/hierarchy-nodes?source=google_drive"
    );
  });

  it("uses the LTI-scoped document endpoint with LTI context", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        documents: [],
        next_cursor: null,
        page_size: 50,
        sort_field: "last_updated",
        sort_direction: "desc",
        folder_position: "on_top",
      }),
    });

    await fetchHierarchyNodeDocuments(
      {
        parent_hierarchy_node_id: 123,
        sort_field: "last_updated",
        sort_direction: "desc",
        folder_position: "on_top",
      },
      "course A/B"
    );

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/auth/lti/course/course%20A%2FB/knowledge/hierarchy-nodes/documents",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          parent_hierarchy_node_id: 123,
          sort_field: "last_updated",
          sort_direction: "desc",
          folder_position: "on_top",
        }),
      })
    );
  });
});
