import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useFormikContext } from "formik";

import SeafileConnectorConfigEditModal from "./SeafileConnectorConfigEditModal";
import {
  normalizeSeafileConnectorConfig,
  SeafileConnectorConfigSchema,
} from "./seafileConfig";
import { updateSeafileConnectorConfig } from "./seafileConnectorUpdate";
import type { CCPairFullInfo } from "./types";
import { ValidSources } from "@/lib/types";

jest.mock("@/components/admin/connectors/seafile/SeafileLibraryPicker", () => {
  function MockSeafileLibraryPicker() {
    const { setFieldValue } = useFormikContext<Record<string, any>>();
    return (
      <button
        type="button"
        onClick={() =>
          setFieldValue("repo_ids", ["repo-2", "repo-1", "repo-2"])
        }
      >
        Select test libraries
      </button>
    );
  }

  return MockSeafileLibraryPicker;
});

const credential = {
  id: 42,
  credential_json: { seafile_api_token: "masked" },
  admin_public: true,
  source: ValidSources.Seafile,
  user_id: null,
  user_email: null,
  time_created: "2026-01-01T00:00:00Z",
  time_updated: "2026-01-01T00:00:00Z",
};

describe("Seafile connector config editing", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("normalizes list values and validates supported extensions", async () => {
    expect(
      normalizeSeafileConnectorConfig({
        base_url: " https://seafile.example.com/ ",
        repo_ids: [" repo-1 ", "repo-1", ""],
        path_prefixes: ["docs/", " /teams ", ""],
        allowed_extensions: ["txt", ".MD", "txt", ""],
        max_file_size_bytes: 100,
      })
    ).toEqual({
      base_url: "https://seafile.example.com/",
      repo_ids: ["repo-1"],
      path_prefixes: ["/docs", "/teams"],
      allowed_extensions: [".txt", ".md"],
      max_file_size_bytes: 100,
    });

    await expect(
      SeafileConnectorConfigSchema.validate({
        base_url: "https://seafile.example.com",
        repo_ids: ["repo-1"],
        path_prefixes: ["/"],
        allowed_extensions: [".zip"],
        max_file_size_bytes: 100,
      })
    ).rejects.toThrow("extensions are not supported");
  });

  it("submits normalized Seafile config from the edit modal", async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined);

    render(
      <SeafileConnectorConfigEditModal
        config={{
          base_url: "https://seafile.example.com",
          repo_ids: ["repo-1"],
          path_prefixes: ["/"],
          allowed_extensions: [".txt"],
          max_file_size_bytes: 200,
        }}
        credential={credential}
        onClose={jest.fn()}
        onSubmit={onSubmit}
      />
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Select test libraries" })
    );
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        base_url: "https://seafile.example.com",
        repo_ids: ["repo-2", "repo-1"],
        path_prefixes: ["/"],
        allowed_extensions: [".txt"],
        max_file_size_bytes: 200,
      });
    });
  });

  it("patches connector config without triggering indexing", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [{ cc_pair_id: 11, groups: [7, 9] }],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
      });
    global.fetch = fetchMock;

    const ccPair = {
      id: 11,
      access_type: "private",
      connector: {
        id: 101,
        name: "Seafile",
        source: "seafile",
        input_type: "poll",
        refresh_freq: 1800,
        prune_freq: 86400,
        indexing_start: null,
      },
    } as CCPairFullInfo;

    await updateSeafileConnectorConfig(ccPair, {
      base_url: "https://seafile.example.com",
      repo_ids: ["repo-2"],
      path_prefixes: ["/docs"],
      allowed_extensions: ["txt"],
      max_file_size_bytes: 300,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/manage/admin/connector/status"
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/manage/admin/connector/101",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          name: "Seafile",
          source: "seafile",
          input_type: "poll",
          connector_specific_config: {
            base_url: "https://seafile.example.com",
            repo_ids: ["repo-2"],
            path_prefixes: ["/docs"],
            allowed_extensions: [".txt"],
            max_file_size_bytes: 300,
          },
          refresh_freq: 1800,
          prune_freq: 86400,
          indexing_start: null,
          access_type: "private",
          groups: [7, 9],
        }),
      })
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/manage/admin/connector/run-once",
      expect.anything()
    );
  });
});
