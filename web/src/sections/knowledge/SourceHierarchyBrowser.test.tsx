import { useState } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  DocumentSummary,
  DocumentPageCursor,
  HierarchyNodeDocumentsResponse,
} from "@/lib/hierarchy/interfaces";
import SourceHierarchyBrowser from "@/sections/knowledge/SourceHierarchyBrowser";
import { ValidSources } from "@/lib/types";
import {
  fetchHierarchyNodes,
  fetchHierarchyNodeDocuments,
} from "@/lib/hierarchy/svc";

jest.mock("@/lib/hierarchy/svc");

const nodes = [
  { id: 1, title: "Course materials", parent_id: null, link: null },
  { id: 2, title: "Week 1", parent_id: 1, link: null },
  { id: 3, title: "Readings", parent_id: 2, link: null },
  { id: 4, title: "Other materials", parent_id: null, link: null },
];

function renderBrowser(
  initialFolderIds: number[] = [],
  restrictToRootNodeId: number | null = null,
  initialDocuments: DocumentSummary[] = [],
  ltiCourseId: string | null = null
) {
  const onSetDocumentIds = jest.fn<void, [string[]]>();
  const onSetFolderIds = jest.fn<void, [number[]]>();
  const onToggleDocument = jest.fn();
  const onToggleFolder = jest.fn();
  const onSelectionPendingChange = jest.fn();

  function Browser() {
    const [folderIds, setFolderIds] = useState(initialFolderIds);
    const [documentIds, setDocumentIds] = useState(
      initialDocuments.map((document) => document.id)
    );

    return (
      <SourceHierarchyBrowser
        source={ValidSources.Canvas}
        onSelectionPendingChange={onSelectionPendingChange}
        restrictToRootNodeId={restrictToRootNodeId}
        ltiCourseId={ltiCourseId}
        initialAttachedDocuments={initialDocuments.map((document) => ({
          ...document,
          source: ValidSources.Canvas,
        }))}
        selectedFolderIds={folderIds}
        selectedDocumentIds={documentIds}
        onToggleFolder={(id) => {
          onToggleFolder(id);
          setFolderIds((ids) =>
            ids.includes(id)
              ? ids.filter((value) => value !== id)
              : [...ids, id]
          );
        }}
        onToggleDocument={(id) => {
          onToggleDocument(id);
          setDocumentIds((ids) =>
            ids.includes(id)
              ? ids.filter((value) => value !== id)
              : [...ids, id]
          );
        }}
        onSetFolderIds={(ids) => {
          onSetFolderIds(ids);
          setFolderIds(ids);
        }}
        onSetDocumentIds={(ids) => {
          onSetDocumentIds(ids);
          setDocumentIds(ids);
        }}
        onDeselectAllFolders={() => setFolderIds([])}
        onDeselectAllDocuments={() => setDocumentIds([])}
      />
    );
  }

  const view = render(
    <TooltipPrimitive.Provider>
      <Browser />
    </TooltipPrimitive.Provider>
  );
  return {
    ...view,
    onSetDocumentIds,
    onSetFolderIds,
    onToggleDocument,
    onToggleFolder,
    onSelectionPendingChange,
  };
}

async function getFolderRow(title: string) {
  const checkbox = await screen.findByRole("checkbox", {
    name: `Select folder ${title}`,
  });
  const row = checkbox.closest(".table-row-layout");
  if (!(row instanceof HTMLElement))
    throw new Error(`Missing row for ${title}`);
  return row;
}

async function openFolder(title: string) {
  const row = await getFolderRow(title);
  await act(async () => {
    fireEvent.click(row);
  });
}

async function toggleCheckbox(name: string) {
  const checkbox = await screen.findByRole("checkbox", { name });
  await act(async () => {
    fireEvent.click(checkbox);
  });
}

function documentForFolder(id: number): DocumentSummary {
  return {
    id: `document-${id}`,
    title: `File in folder ${id}`,
    parent_id: id,
    link: null,
    last_modified: null,
    last_synced: null,
  };
}

function documentPage(
  documents: DocumentSummary[],
  nextCursor: DocumentPageCursor | null = null
): HierarchyNodeDocumentsResponse {
  return {
    documents,
    next_cursor: nextCursor,
    page_size: 100,
    sort_field: "name",
    sort_direction: "asc",
    folder_position: "on_top",
  };
}

beforeEach(() => {
  jest.mocked(fetchHierarchyNodes).mockReset();
  jest.mocked(fetchHierarchyNodeDocuments).mockReset();
  jest.mocked(fetchHierarchyNodes).mockResolvedValue({ nodes });
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockImplementation(async (request) => ({
      documents: [
        {
          id: `document-${request.parent_hierarchy_node_id}`,
          title: `File in folder ${request.parent_hierarchy_node_id}`,
          parent_id: request.parent_hierarchy_node_id,
          link: null,
          last_modified: null,
          last_synced: null,
        },
      ],
      next_cursor: null,
      page_size: 100,
      sort_field: "last_updated",
      sort_direction: "desc",
      folder_position: "on_top",
    }));
});

test("selecting a folder checks its files and nested folders while browsing", async () => {
  renderBrowser();
  await toggleCheckbox("Select folder Course materials");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Other materials" })
  ).toHaveAttribute("aria-checked", "false");
  await openFolder("Course materials");

  expect(
    await screen.findByRole("checkbox", {
      name: "Select document File in folder 1",
    })
  ).toHaveAttribute("aria-checked", "true");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Week 1" })
  ).toHaveAttribute("aria-checked", "true");
  expect(
    screen.getByRole("checkbox", { name: "Select all items" })
  ).toHaveAttribute("aria-checked", "true");

  await openFolder("Week 1");
  expect(
    await screen.findByRole("checkbox", {
      name: "Select document File in folder 2",
    })
  ).toHaveAttribute("aria-checked", "true");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Readings" })
  ).toHaveAttribute("aria-checked", "true");

  await openFolder("Readings");
  expect(
    await screen.findByRole("checkbox", {
      name: "Select document File in folder 3",
    })
  ).toHaveAttribute("aria-checked", "true");
});

test("existing course-folder selections stay inherited without adding attachments", async () => {
  const actions = renderBrowser([1], 1);
  const file = await screen.findByRole("checkbox", {
    name: "Select document File in folder 1",
  });
  expect(file).toHaveAttribute("aria-checked", "true");
  expect(file.parentElement?.querySelector("input")).not.toBeDisabled();

  const folderRow = await getFolderRow("Week 1");
  const header = screen.getByRole("checkbox", { name: "Select all items" });
  expect(header).toHaveAttribute("aria-checked", "true");
  expect(header.parentElement?.querySelector("input")).not.toBeDisabled();

  await act(async () => {
    fireEvent.click(folderRow);
  });
  expect(actions.onToggleDocument).not.toHaveBeenCalled();
  expect(actions.onToggleFolder).not.toHaveBeenCalled();
  expect(actions.onSetDocumentIds).not.toHaveBeenCalled();
  expect(actions.onSetFolderIds).not.toHaveBeenCalled();
  expect(screen.getByText("1 item selected")).toBeInTheDocument();
});

test("deselecting a parent clears all of its descendants", async () => {
  renderBrowser([1, 3]);
  await openFolder("Course materials");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Canvas" }));
  });
  await toggleCheckbox("Select folder Course materials");
  await openFolder("Course materials");

  expect(
    await screen.findByRole("checkbox", {
      name: "Select document File in folder 1",
    })
  ).toHaveAttribute("aria-checked", "false");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Week 1" })
  ).toHaveAttribute("aria-checked", "false");

  await openFolder("Week 1");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Readings" })
  ).toHaveAttribute("aria-checked", "false");
  expect(
    screen.getByRole("checkbox", { name: "Select document File in folder 2" })
  ).toHaveAttribute("aria-checked", "false");
  expect(
    screen.getByRole("checkbox", { name: "Select all items" })
  ).toHaveAttribute("aria-checked", "false");
});

test("folder rows open their contents without selecting them", async () => {
  const actions = renderBrowser();
  await openFolder("Course materials");
  expect(
    screen.getByRole("checkbox", { name: "Select document File in folder 1" })
  ).toHaveAttribute("aria-checked", "false");
  expect(actions.onSetFolderIds).not.toHaveBeenCalled();
  expect(actions.onSetDocumentIds).not.toHaveBeenCalled();
});

test("unchecking a nested inherited file preserves siblings and survives reopening", async () => {
  const actions = renderBrowser([1, 4], null, [], "course-123");
  await openFolder("Course materials");
  await openFolder("Week 1");
  await toggleCheckbox("Select document File in folder 2");
  expect(
    screen.getByRole("checkbox", { name: "Select document File in folder 2" })
  ).toHaveAttribute("aria-checked", "false");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Readings" })
  ).toHaveAttribute("aria-checked", "true");
  expect(actions.onSetFolderIds).toHaveBeenLastCalledWith([4, 3]);
  expect(actions.onSetDocumentIds).toHaveBeenLastCalledWith(["document-1"]);
  expect(
    jest
      .mocked(fetchHierarchyNodeDocuments)
      .mock.calls.every(([, courseId]) => courseId === "course-123")
  ).toBe(true);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Canvas" }));
  });
  expect(
    screen.getByRole("checkbox", { name: "Select folder Course materials" })
  ).toHaveAttribute("aria-checked", "mixed");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Other materials" })
  ).toHaveAttribute("aria-checked", "true");

  actions.unmount();
  renderBrowser([4, 3], null, [
    {
      id: "document-1",
      title: "File in folder 1",
      parent_id: 1,
      link: null,
      last_modified: null,
      last_synced: null,
    },
  ]);
  expect(
    await screen.findByRole("checkbox", {
      name: "Select folder Course materials",
    })
  ).toHaveAttribute("aria-checked", "mixed");
  await openFolder("Course materials");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Week 1" })
  ).toHaveAttribute("aria-checked", "mixed");
});

test("selecting the last individual file checks the parent and checking a partial parent selects everything", async () => {
  const actions = renderBrowser();
  await openFolder("Course materials");
  await openFolder("Week 1");
  await openFolder("Readings");
  await toggleCheckbox("Select document File in folder 3");
  expect(actions.onSetFolderIds).toHaveBeenLastCalledWith([3]);
  expect(actions.onSetDocumentIds).toHaveBeenLastCalledWith([]);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Week 1" }));
  });
  expect(
    screen.getByRole("checkbox", { name: "Select folder Readings" })
  ).toHaveAttribute("aria-checked", "true");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Course materials" }));
  });
  expect(
    screen.getByRole("checkbox", { name: "Select folder Week 1" })
  ).toHaveAttribute("aria-checked", "mixed");
  await toggleCheckbox("Select folder Week 1");
  await openFolder("Week 1");
  expect(
    screen.getByRole("checkbox", { name: "Select all items" })
  ).toHaveAttribute("aria-checked", "true");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Course materials" }));
  });
  await toggleCheckbox("Select document File in folder 1");
  expect(actions.onSetFolderIds).toHaveBeenLastCalledWith([1]);
  expect(actions.onSetDocumentIds).toHaveBeenLastCalledWith([]);
  actions.unmount();
  renderBrowser([1]);
  expect(
    await screen.findByRole("checkbox", {
      name: "Select folder Course materials",
    })
  ).toHaveAttribute("aria-checked", "true");
});

test("files loaded by pagination inherit the selected folder", async () => {
  jest.mocked(fetchHierarchyNodeDocuments).mockResolvedValueOnce({
    documents: [],
    next_cursor: { document_id: "previous-file" },
    page_size: 100,
    sort_field: "last_updated",
    sort_direction: "desc",
    folder_position: "on_top",
  });
  renderBrowser([1], 1);
  const folderRow = await getFolderRow("Week 1");
  const scrollContainer = folderRow.closest(".overflow-y-auto");
  if (!scrollContainer) throw new Error("Missing scroll container");
  await act(async () => {
    fireEvent.scroll(scrollContainer);
  });

  expect(fetchHierarchyNodeDocuments).toHaveBeenLastCalledWith(
    expect.objectContaining({ cursor: { document_id: "previous-file" } }),
    null
  );
  expect(
    await screen.findByRole("checkbox", {
      name: "Select document File in folder 1",
    })
  ).toHaveAttribute("aria-checked", "true");
});

test("unchecking an inherited subfolder clears its subtree and keeps its parent's files", async () => {
  const actions = renderBrowser([1, 3, 4]);
  await openFolder("Course materials");
  await toggleCheckbox("Select folder Week 1");
  expect(actions.onSetFolderIds).toHaveBeenLastCalledWith([4]);
  expect(actions.onSetDocumentIds).toHaveBeenLastCalledWith(["document-1"]);
  expect(
    screen.getByRole("checkbox", { name: "Select document File in folder 1" })
  ).toHaveAttribute("aria-checked", "true");
  await openFolder("Week 1");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Readings" })
  ).toHaveAttribute("aria-checked", "false");
});

test("bulk selection can select and clear a folder's visible contents", async () => {
  const actions = renderBrowser();
  await openFolder("Course materials");
  await toggleCheckbox("Select all items");
  expect(
    screen.getByRole("checkbox", { name: "Select all items" })
  ).toHaveAttribute("aria-checked", "true");
  await toggleCheckbox("Select all items");
  expect(actions.onSetFolderIds).toHaveBeenLastCalledWith([]);
  expect(actions.onSetDocumentIds).toHaveBeenLastCalledWith([]);
});

test("splitting a selected ancestor retains files from every page", async () => {
  const unloadedFile = {
    ...documentForFolder(1),
    id: "unloaded-file",
    title: "Unloaded file",
  };
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockImplementation(async (request) => {
      if (request.parent_hierarchy_node_id !== 1)
        return documentPage([
          documentForFolder(request.parent_hierarchy_node_id),
        ]);
      if (request.cursor) return documentPage([unloadedFile]);
      return documentPage([documentForFolder(1)], {
        document_id: "document-1",
      });
    });
  const actions = renderBrowser([1]);
  await openFolder("Course materials");
  await openFolder("Week 1");
  await toggleCheckbox("Select document File in folder 2");
  expect(actions.onSetDocumentIds).toHaveBeenLastCalledWith([
    "document-1",
    "unloaded-file",
  ]);
  expect(fetchHierarchyNodeDocuments).toHaveBeenCalledWith(
    expect.objectContaining({
      parent_hierarchy_node_id: 1,
      sort_field: "name",
      cursor: { document_id: "document-1" },
    }),
    null
  );
});

test("failed ancestor loading keeps the selection and allows retrying", async () => {
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockResolvedValueOnce(
      documentPage([documentForFolder(1)], { document_id: "document-1" })
    );
  const actions = renderBrowser([1]);
  await openFolder("Course materials");
  await openFolder("Week 1");
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockRejectedValueOnce(new Error("Server error"));
  const consoleError = jest.spyOn(console, "error").mockImplementation();
  try {
    await toggleCheckbox("Select document File in folder 2");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Your previous selection was kept"
    );
    expect(
      screen.getByRole("checkbox", { name: "Select document File in folder 2" })
    ).toHaveAttribute("aria-checked", "true");
    expect(actions.onSetFolderIds).not.toHaveBeenCalled();
    expect(actions.onSetDocumentIds).not.toHaveBeenCalled();
    expect(actions.onSelectionPendingChange).toHaveBeenCalledWith(true);
    expect(actions.onSelectionPendingChange).toHaveBeenLastCalledWith(false);
    await toggleCheckbox("Select document File in folder 2");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select document File in folder 2" })
    ).toHaveAttribute("aria-checked", "false");
  } finally {
    consoleError.mockRestore();
  }
});

test("unmounting cancels a pending selection and clears its pending state", async () => {
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockResolvedValueOnce(
      documentPage([documentForFolder(1)], { document_id: "document-1" })
    );
  const actions = renderBrowser([1]);
  await openFolder("Course materials");
  await openFolder("Week 1");
  let resolvePage!: (page: HierarchyNodeDocumentsResponse) => void;
  jest.mocked(fetchHierarchyNodeDocuments).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolvePage = resolve;
      })
  );

  await toggleCheckbox("Select document File in folder 2");
  expect(actions.onSelectionPendingChange).toHaveBeenLastCalledWith(true);
  actions.unmount();

  await act(async () => {
    resolvePage(documentPage([documentForFolder(1)]));
  });
  expect(actions.onSetFolderIds).not.toHaveBeenCalled();
  expect(actions.onSetDocumentIds).not.toHaveBeenCalled();
  expect(actions.onSelectionPendingChange).toHaveBeenLastCalledWith(false);
});

test("a failed file request shows an error and can be retried", async () => {
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockRejectedValueOnce(new Error("Server error"));
  const consoleError = jest.spyOn(console, "error").mockImplementation();
  try {
    renderBrowser([], 3);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to load files in this folder."
    );
    expect(
      screen.queryByText("No items in this folder.")
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry files" }));
    expect(
      await screen.findByRole("checkbox", {
        name: "Select document File in folder 3",
      })
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  } finally {
    consoleError.mockRestore();
  }
});

test("pagination errors keep loaded files and retry the failed page", async () => {
  jest.mocked(fetchHierarchyNodeDocuments).mockResolvedValueOnce({
    documents: [
      {
        id: "first-file",
        title: "First file",
        parent_id: 1,
        link: null,
        last_modified: null,
        last_synced: null,
      },
    ],
    next_cursor: { document_id: "first-file" },
    page_size: 100,
    sort_field: "last_updated",
    sort_direction: "desc",
    folder_position: "on_top",
  });
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockRejectedValueOnce(new Error("Server error"));
  const consoleError = jest.spyOn(console, "error").mockImplementation();
  try {
    renderBrowser([], 1);
    const file = await screen.findByRole("checkbox", {
      name: "Select document First file",
    });
    const scrollContainer = file.closest(".overflow-y-auto");
    if (!scrollContainer) throw new Error("Missing scroll container");
    fireEvent.scroll(scrollContainer);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(file).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry files" }));
    expect(
      await screen.findByRole("checkbox", {
        name: "Select document File in folder 1",
      })
    ).toBeInTheDocument();
    expect(fetchHierarchyNodeDocuments).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: { document_id: "first-file" } }),
      null
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  } finally {
    consoleError.mockRestore();
  }
});
