import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Formik } from "formik";
import SeafileLibraryPicker from "./SeafileLibraryPicker";
import { Credential } from "@/lib/connectors/credentials";

const credential: Credential<{ seafile_api_token: string }> = {
  id: 42,
  credential_json: { seafile_api_token: "masked" },
  admin_public: true,
  source: "seafile",
  user_id: null,
  user_email: null,
  time_created: "2026-01-01T00:00:00Z",
  time_updated: "2026-01-01T00:00:00Z",
};

function renderPicker(
  fetchImpl: jest.Mock,
  onSubmit: jest.Mock = jest.fn(),
  repoIds: string[] = []
) {
  global.fetch = fetchImpl;

  return render(
    <Formik
      initialValues={{
        base_url: "https://seafile.example.com",
        repo_ids: repoIds,
      }}
      onSubmit={onSubmit}
    >
      {({ values, submitForm }) => (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submitForm();
          }}
        >
          <SeafileLibraryPicker
            currentCredential={credential}
            label="Library IDs"
            description="Select libraries"
          />
          <output data-testid="repo-ids">
            {JSON.stringify(values.repo_ids)}
          </output>
          <button type="submit">Submit</button>
        </form>
      )}
    </Formik>
  );
}

describe("SeafileLibraryPicker", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("fetches libraries and writes selected ids to repo_ids", async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { id: "repo-1", name: "Engineering", owner: "admin" },
        { id: "repo-2", name: "Product" },
      ],
    });
    renderPicker(fetchMock);

    const engineering = await screen.findByLabelText(/Engineering/);
    await userEvent.click(engineering);
    await userEvent.click(screen.getByLabelText(/Product/));

    expect(screen.getByTestId("repo-ids")).toHaveTextContent(
      JSON.stringify(["repo-1", "repo-2"])
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/manage/admin/connector/seafile/libraries",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          base_url: "https://seafile.example.com",
          credential_id: 42,
        }),
      })
    );
  });

  it("keeps manual repo id entry available when fetch fails", async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Cannot list libraries" }),
    });
    renderPicker(fetchMock);

    await waitFor(() => {
      expect(screen.getByText("Cannot list libraries")).toBeInTheDocument();
    });
    expect(screen.getByText("Manual Library IDs")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Add New/i })
    ).toBeInTheDocument();
  });

  it("deduplicates discovered libraries that share a Seafile repo id", async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: "repo-1@auth.local",
          name: "Shared",
          owner: "user@auth.local",
        },
        { id: "repo-1", name: "Shared", owner: "Organization" },
        { id: "repo-2", name: "Workspace" },
      ],
    });
    renderPicker(fetchMock, jest.fn(), ["repo-1"]);

    await waitFor(() => {
      expect(screen.getByLabelText(/Shared/)).toBeChecked();
    });

    expect(screen.getAllByText("Shared")).toHaveLength(1);
    expect(screen.getByTestId("repo-ids")).toHaveTextContent(
      JSON.stringify(["repo-1"])
    );
  });
});
