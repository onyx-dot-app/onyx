/**
 * Guards the duplicate-attachment regression introduced by react-dropzone 20.
 *
 * react-dropzone 20 added paste-to-upload and enables it by default. Our
 * composers already upload pasted files themselves, and their paste handlers
 * call preventDefault without stopPropagation, so the event keeps bubbling to
 * the dropzone root. A dropzone wrapping a composer therefore uploads every
 * pasted file a second time. `noPaste` turns the library's paste handling off.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { act, render, waitFor } from "@testing-library/react";
import Dropzone from "react-dropzone";

const WEB_ROOT = path.resolve(__dirname, "../../../..");

/** Dropzones that wrap a composer which already handles paste itself. */
const COMPOSER_DROPZONE_FILES = [
  "src/views/AppPage.tsx",
  "src/app/nrf/NRFPage.tsx",
  "src/app/craft/components/ChatPanel.tsx",
];

async function firePasteWithFile(el: Element): Promise<void> {
  const file = new File(["image-bytes"], "image.png", { type: "image/png" });
  const event = new Event("paste", { bubbles: true, cancelable: true });
  // jsdom has no DataTransfer, and react-dropzone only reads `types`/`items`
  // off the clipboard, so a plain stand-in is enough to drive the real handler.
  Object.defineProperty(event, "clipboardData", {
    value: {
      types: ["Files"],
      items: [{ kind: "file", type: "image/png", getAsFile: () => file }],
      files: [file],
    },
  });
  await act(async () => {
    el.dispatchEvent(event);
  });
}

function renderComposerInsideDropzone(noPaste: boolean) {
  const onDrop = jest.fn();
  const composerPaste = jest.fn();
  const view = render(
    <Dropzone onDrop={onDrop} noClick noPaste={noPaste}>
      {({ getRootProps }) => (
        <div {...getRootProps()}>
          <div
            data-testid="composer"
            contentEditable
            suppressContentEditableWarning
            onPaste={composerPaste}
          />
        </div>
      )}
    </Dropzone>
  );
  return { onDrop, composerPaste, view };
}

describe("pasting a file into a composer wrapped in a dropzone", () => {
  // Control case. Without it the assertion below could pass for the wrong
  // reason — e.g. if the stand-in event stopped reaching react-dropzone at all.
  // It also fails loudly if the library ever stops handling paste by default,
  // which is the day `noPaste` becomes unnecessary.
  it("reaches react-dropzone when noPaste is not set", async () => {
    const { onDrop, composerPaste } = renderComposerInsideDropzone(false);

    await firePasteWithFile(
      document.querySelector('[data-testid="composer"]')!
    );

    await waitFor(() => expect(onDrop).toHaveBeenCalledTimes(1));
    expect(composerPaste).toHaveBeenCalledTimes(1);
  });

  it("is handled only by the composer when noPaste is set", async () => {
    const { onDrop, composerPaste } = renderComposerInsideDropzone(true);

    await firePasteWithFile(
      document.querySelector('[data-testid="composer"]')!
    );

    await waitFor(() => expect(composerPaste).toHaveBeenCalledTimes(1));
    // Give the library's async file read a chance to land before asserting.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onDrop).not.toHaveBeenCalled();
  });
});

/**
 * Every `<Dropzone ...>` opening tag in `source`.
 *
 * Brace-aware on purpose: a prop value like `onDrop={(files) => ...}` contains
 * a `>`, so the tag cannot be matched with a naive `[^>]*`. Slicing the tag
 * itself also keeps surrounding comments out of the assertion — matching the
 * bare word anywhere in the file would be satisfied by a comment mentioning it.
 */
function dropzoneOpeningTags(source: string): string[] {
  const tags: string[] = [];
  let start = source.indexOf("<Dropzone");
  while (start !== -1) {
    let depth = 0;
    let end = start;
    while (end < source.length) {
      const char = source[end];
      if (char === "{") depth += 1;
      else if (char === "}") depth -= 1;
      else if (char === ">" && depth === 0) break;
      end += 1;
    }
    tags.push(source.slice(start, end + 1));
    start = source.indexOf("<Dropzone", end);
  }
  return tags;
}

describe("composer dropzones opt out of paste-to-upload", () => {
  // These pages need the full app provider tree to render, so the call sites
  // are guarded at the source level instead. Cheap, and it is what stops a
  // future edit from silently restoring duplicate uploads.
  it.each(COMPOSER_DROPZONE_FILES)("%s passes noPaste", (relativePath) => {
    const source = fs.readFileSync(path.join(WEB_ROOT, relativePath), "utf8");
    const tags = dropzoneOpeningTags(source);

    expect(tags.length).toBeGreaterThan(0);
    for (const tag of tags) {
      expect(tag).toMatch(/\bnoPaste\b/);
    }
  });
});
