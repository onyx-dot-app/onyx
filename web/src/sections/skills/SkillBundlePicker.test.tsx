import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { prepareSkillBundleUpload } from "@/lib/skills/bundleUpload";
import SkillBundlePicker from "./SkillBundlePicker";

jest.mock("@/lib/skills/bundleUpload", () => ({
  prepareSkillBundleUpload: jest.fn(),
}));

const mockedPrepareSkillBundleUpload = jest.mocked(prepareSkillBundleUpload);

function dropFile(file: File): void {
  fireEvent.drop(screen.getByTestId("skill-bundle-dropzone"), {
    dataTransfer: {
      files: [file],
      items: [
        {
          kind: "file",
          type: file.type,
          getAsFile: () => file,
        },
      ],
      types: ["Files"],
    },
  });
}

function directoryFileEntry(path: string, file: File) {
  return {
    isDirectory: false,
    fullPath: path,
    file: (resolve: (value: File) => void) => resolve(file),
  };
}

function dropDirectory(files: Array<{ path: string; file: File }>): void {
  let readCount = 0;
  const directoryEntry = {
    isDirectory: true,
    createReader: () => ({
      readEntries: (resolve: (entries: unknown[]) => void) => {
        resolve(
          readCount++ === 0
            ? files.map(({ path, file }) => directoryFileEntry(path, file))
            : []
        );
      },
    }),
  };

  fireEvent.drop(screen.getByTestId("skill-bundle-dropzone"), {
    dataTransfer: {
      files: [],
      items: [
        {
          kind: "file",
          type: "",
          webkitGetAsEntry: () => directoryEntry,
        },
      ],
      types: ["Files"],
    },
  });
}

describe("SkillBundlePicker", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("owns preparation state without waiting for consumer work", async () => {
    const zip = new File(["zip"], "example.zip", { type: "application/zip" });
    const prepared = {
      file: zip,
      displayName: "example.zip",
      source: "zip" as const,
    };
    mockedPrepareSkillBundleUpload.mockResolvedValue(prepared);

    const onChange = jest.fn(() => new Promise<void>(() => undefined));
    const onPreparingChange = jest.fn();

    render(
      <SkillBundlePicker
        value={null}
        onChange={onChange}
        onError={jest.fn()}
        onPreparingChange={onPreparingChange}
      />
    );

    dropFile(zip);

    await waitFor(() => {
      expect(mockedPrepareSkillBundleUpload).toHaveBeenCalledWith([zip]);
      expect(onChange).toHaveBeenCalledWith(prepared);
    });
    expect(onPreparingChange).toHaveBeenCalledWith(true);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Choose a ZIP file" })
      ).toBeEnabled();
      expect(onPreparingChange).toHaveBeenLastCalledWith(false);
    });
  });

  it("reports preparation failures without submitting an upload", async () => {
    const invalidFolderFile = new File(["body"], "notes.md", {
      type: "text/markdown",
    });
    mockedPrepareSkillBundleUpload.mockRejectedValue(
      new Error("The selected folder must contain SKILL.md at its top level.")
    );
    const onChange = jest.fn();
    const onError = jest.fn();

    render(
      <SkillBundlePicker value={null} onChange={onChange} onError={onError} />
    );

    dropFile(invalidFolderFile);

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith(
        "The selected folder must contain SKILL.md at its top level."
      );
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("passes recursively dropped directory files with their full paths", async () => {
    const skillMd = new File(["instructions"], "SKILL.md");
    const helper = new File(["print('hello')"], "helper.py");
    mockedPrepareSkillBundleUpload.mockResolvedValue({
      file: new File(["zip"], "example.zip"),
      displayName: "example",
      source: "folder",
    });

    render(
      <SkillBundlePicker
        value={null}
        onChange={jest.fn()}
        onError={jest.fn()}
      />
    );

    dropDirectory([
      { path: "/example/SKILL.md", file: skillMd },
      { path: "/example/scripts/helper.py", file: helper },
    ]);

    await waitFor(() => {
      expect(mockedPrepareSkillBundleUpload).toHaveBeenCalledTimes(1);
    });
    const droppedFiles = mockedPrepareSkillBundleUpload.mock.calls[0]![0];
    expect(droppedFiles.map((file) => file.path)).toEqual([
      "/example/SKILL.md",
      "/example/scripts/helper.py",
    ]);
  });
});
