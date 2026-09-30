import {
  getCreatedConnectorId,
  type ConnectorCreationResponse,
} from "@/views/admin/connectors/AddConnectorPage/creationResponse";

describe("getCreatedConnectorId", () => {
  it("reads the standard connector creation response", () => {
    const response: ConnectorCreationResponse = {
      id: 17,
      credential: null,
    };

    expect(getCreatedConnectorId(response)).toBe(17);
  });

  it("reads the mock-credential connector creation response", () => {
    const response: ConnectorCreationResponse = {
      success: true,
      message: "Created connector-credential pair",
      data: 29,
      connector_id: 23,
    };

    expect(getCreatedConnectorId(response)).toBe(23);
  });
});
