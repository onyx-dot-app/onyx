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

describe("SkillBundlePicker", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("prepares a dropped upload and remains locked until the consumer finishes", async () => {
    const zip = new File(["zip"], "example.zip", { type: "application/zip" });
    const prepared = {
      file: zip,
      displayName: "example.zip",
      source: "zip" as const,
    };
    mockedPrepareSkillBundleUpload.mockResolvedValue(prepared);

    let finishUpload: () => void = () => undefined;
    const onChange = jest.fn(
      () =>
        new Promise<void>((resolve) => {
          finishUpload = resolve;
        })
    );
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
    expect(
      screen.getByRole("button", { name: "Preparing upload..." })
    ).toBeDisabled();
    expect(onPreparingChange).toHaveBeenCalledWith(true);

    finishUpload();

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
});
