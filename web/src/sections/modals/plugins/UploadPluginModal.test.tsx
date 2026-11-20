import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import type { PluginUploadPreview } from "@/lib/plugins/types";
import type { PreparedSkillBundle } from "@/lib/skills/bundleUpload";
import UploadPluginModal from "@/sections/modals/plugins/UploadPluginModal";

jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: false,
    isScopedManager: false,
  }),
}));

// The zip reader needs streams that jsdom lacks; upload.test.ts covers it.
let mockKindReads = 0;
jest.mock("@/lib/plugins/upload", () => ({
  pluginUploadKind: async ({ file }: { file: File }) => {
    mockKindReads += 1;
    return file.name.startsWith("skill-") ? "skill" : "plugin";
  },
}));

let mockPendingPrepare: Promise<PreparedSkillBundle> | null = null;
jest.mock("@/lib/skills/bundleUpload", () => {
  const actual = jest.requireActual("@/lib/skills/bundleUpload");
  return {
    ...actual,
    prepareSkillBundleUpload: (...args: unknown[]) =>
      mockPendingPrepare ?? actual.prepareSkillBundleUpload(...args),
  };
});

afterEach(() => {
  mockPendingPrepare = null;
  mockKindReads = 0;
  jest.restoreAllMocks();
});

function zip(name: string): File {
  return new File(["zip"], name, { type: "application/zip" });
}

function preview(over: Partial<PluginUploadPreview> = {}): PluginUploadPreview {
  return {
    manifest: {
      name: "review-kit",
      version: "1.2.0",
      description: "Review pull requests.",
      author: null,
      homepage: null,
      repository: null,
      license: null,
      keywords: [],
      unused_parts: ["commands"],
    },
    skills: [
      {
        path: "skills/review",
        name: "review",
        description: "Review a diff.",
        warnings: [],
      },
    ],
    needs: [
      {
        kind: "mcp",
        name: "linear",
        url: "https://mcp.linear.app/mcp",
        transport: "http",
        url_problem: null,
        supported: true,
        state: "not_added",
        integration_id: null,
      },
    ],
    warnings: [],
    target: {
      kind: "new_version",
      plugin_id: "11111111-1111-4111-8111-111111111111",
      plugin_name: "review-kit",
      version_number: 3,
    },
    will_enable: true,
    name_conflicts: [],
    ...over,
  };
}

function formValue(init: RequestInit | undefined, key: string) {
  return init?.body instanceof FormData ? init.body.get(key) : null;
}

function renderModal() {
  const onSaved = jest.fn();
  const onContinueSkill = jest.fn();
  render(
    <UploadPluginModal
      open
      onClose={jest.fn()}
      onSaved={onSaved}
      onContinueSkill={onContinueSkill}
    />
  );
  return { onSaved, onContinueSkill };
}

async function choose(file: File) {
  const user = setupUser();
  const input = screen
    .getByTestId("skill-bundle-dropzone")
    .querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await user.upload(input, file);
  return user;
}

test("a plugin zip shows the preview and Save as a new plugin re-reads it", async () => {
  const fetchMock = mockFetch({
    "/api/integrations": [],
    "POST /api/skills/plugins/inspect": (init?: RequestInit) =>
      formValue(init, "save_as_new") === "true"
        ? preview({
            target: {
              kind: "new_plugin",
              plugin_id: null,
              plugin_name: "review-kit-2",
              version_number: 1,
            },
          })
        : preview(),
  });
  renderModal();
  const user = await choose(zip("review-kit.zip"));

  expect(
    await screen.findByText("Updates review-kit to Onyx version 3")
  ).toBeInTheDocument();
  expect(screen.getByText("Not added")).toBeInTheDocument();
  expect(screen.getByText("Commands")).toBeInTheDocument();

  await user.click(
    screen.getByRole("checkbox", { name: "Save as a New Plugin" })
  );
  expect(
    await screen.findByText("New plugin: review-kit-2")
  ).toBeInTheDocument();
  const saveAsNew = fetchMock.mock.calls
    .filter(([url]) => String(url) === "/api/skills/plugins/inspect")
    .map(([, init]) => formValue(init, "save_as_new"));
  expect(saveAsNew).toEqual(["false", "true"]);
});

test("a bad zip shows the reason from the server", async () => {
  mockFetch({
    "POST /api/skills/plugins/inspect": new Response(
      JSON.stringify({
        error_code: "INVALID_INPUT",
        detail: "plugin.json needs a 'name'.",
      }),
      { status: 400 }
    ),
  });
  renderModal();
  await choose(zip("bad.zip"));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "plugin.json needs a 'name'."
  );
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});

test("a zip with a skill and no plugin.json continues as a skill", async () => {
  const fetchMock = mockFetch({
    "POST /api/skills/custom/bundle/inspect": {
      name: "notes",
      description: "Take notes.",
      instructions_markdown: "Take notes.",
      files: [],
    },
  });
  const { onContinueSkill } = renderModal();
  const user = await choose(zip("skill-notes.zip"));
  expect(await screen.findByText("This upload is a skill")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(onContinueSkill).toHaveBeenCalledTimes(1));
  expect(onContinueSkill.mock.calls[0][0].contents.name).toBe("notes");
  expect(
    fetchMock.mock.calls.some(
      ([url]) => String(url) === "/api/skills/plugins/inspect"
    )
  ).toBe(false);
});

test("a file that finishes preparing after the modal closes is not read", async () => {
  let finishPrepare: (bundle: PreparedSkillBundle) => void = () => undefined;
  mockPendingPrepare = new Promise((resolve) => {
    finishPrepare = resolve;
  });
  const props = {
    onClose: jest.fn(),
    onSaved: jest.fn(),
    onContinueSkill: jest.fn(),
  };
  const { rerender } = render(<UploadPluginModal open {...props} />);
  await choose(zip("review-kit.zip"));
  rerender(<UploadPluginModal open={false} {...props} />);

  const file = zip("review-kit.zip");
  finishPrepare({ file, displayName: file.name, source: "zip" });
  await mockPendingPrepare;

  expect(mockKindReads).toBe(0);
});

test("a skill name clash says the plugin is saved off", async () => {
  mockFetch({
    "/api/integrations": [],
    "POST /api/skills/plugins/inspect": () =>
      preview({
        target: {
          kind: "new_plugin",
          plugin_id: null,
          plugin_name: "review-kit",
          version_number: 1,
        },
        will_enable: false,
        name_conflicts: ["old-kit"],
      }),
  });
  renderModal();
  await choose(zip("review-kit.zip"));

  expect(
    await screen.findByText(
      "The plugin is saved off. old-kit already has a skill with the same name."
    )
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "The plugin is off after the save, so the save turns on no integrations."
    )
  ).toBeInTheDocument();
});
