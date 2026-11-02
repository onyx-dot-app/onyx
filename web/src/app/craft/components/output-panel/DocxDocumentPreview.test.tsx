import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import DocxDocumentPreview from "@/app/craft/components/output-panel/DocxDocumentPreview";

// Minimal DOCX containing one paragraph; exercises the real ZIP reader and renderer.
const documentBase64 =
  "UEsDBBQAAAAIAAFmVl10JJxTuwAAAD4BAAATAAAAW0NvbnRlbnRfVHlwZXNdLnhtbJWQuQ7CMAyGX6XKiqgRAwNquwArMPACVuq2EbkUuxxvT8o1sDHa//FZrk73SFzcnPVcq0EkrgFYD+SQyxDJZ6ULyaHkMfUQUZ+xJ1guFivQwQt5mcvUoZpqSx2OVordLa/ZBF+rRJZVsXkZJ1atMEZrNErW4eLbH8r8TShz8unhwUSeZYOCpjpcKCXTUnHEJHt0uQ6uIbXQBj26jCgn41+80HVG0zc/tcUUNDEb3ztbfhWHxn/ugOfbmgdQSwMEFAAAAAgAAWZWXWF7L0OJAAAA8gAAAAsAAABfcmVscy8ucmVsc43POw4CIRAG4KsQDrCzWlgYoLLZ1ngBAsMjLo8MGPX2UlisxsJy5p98f0accdU9ltxCrI090pqb5KH3egRoJmDSbSoV80hcoaT7GMlD1eaqPcJ+ng9AW4MrsTXZYiWnxe44uzwr/mMX56LBUzG3hLn/qPi6GLImj13yeyEL9r2eBstBCfh4Ub0AUEsDBBQAAAAIAAFmVl1PQ8DImgAAAN4AAAARAAAAd29yZC9kb2N1bWVudC54bWxFj+sKwjAMhV9l7AFMHSpS5v7sBQSfoHbZBdYLabTq09sWpn++nJAcTtJGOTj9MGi5epnVBhkv9czsJUDQMxoVds6jTbPRkVGcWpogOho8OY0hLHYyKzRCnMCoxdZdG+XdDe9cfQZlcNeTGrn6hXnC54KxhTzLpMLiCKj5Wmx+un2qmG/aN81B1EnPSR/PSUMxbLuwpcL/o+4LUEsBAhQDFAAAAAgAAWZWXXQknFO7AAAAPgEAABMAAAAAAAAAAAAAAIABAAAAAFtDb250ZW50X1R5cGVzXS54bWxQSwECFAMUAAAACAABZlZdYXsvQ4kAAADyAAAACwAAAAAAAAAAAAAAgAHsAAAAX3JlbHMvLnJlbHNQSwECFAMUAAAACAABZlZdT0PAyJoAAADeAAAAEQAAAAAAAAAAAAAAgAGeAQAAd29yZC9kb2N1bWVudC54bWxQSwUGAAAAAAMAAwC5AAAAZwIAAAAA";

it("renders a DOCX document and reopens cached content without a loading flash", async () => {
  const bytes = new Uint8Array(Buffer.from(documentBase64, "base64"));
  const blob = Object.assign(new Blob([bytes]), {
    arrayBuffer: jest.fn(async () => bytes.buffer),
  });
  const onError = jest.fn();
  const first = render(
    <DocxDocumentPreview blob={blob} onError={onError} initialScrollTop={240} />
  );
  const host = first.container.querySelector(".docx-host");
  const scrollArea = host?.parentElement;
  expect(scrollArea?.scrollTop).toBe(0);
  await waitFor(() =>
    expect(host?.shadowRoot?.textContent).toContain("Craft document preview")
  );
  expect(scrollArea?.scrollTop).toBe(240);
  expect(first.container.querySelector("style")).toBeNull();
  expect(onError).not.toHaveBeenCalled();
  first.unmount();
  const second = render(
    <DocxDocumentPreview blob={blob} onError={onError} initialScrollTop={240} />
  );
  const reopened = second.container.querySelector(".docx-host");
  expect(reopened?.shadowRoot?.textContent).toContain("Craft document preview");
  expect(reopened?.parentElement?.scrollTop).toBe(240);
  expect(screen.queryByText("Loading file")).not.toBeInTheDocument();
  expect(blob.arrayBuffer).toHaveBeenCalledTimes(1);
});

it.each([true, false])(
  "preserves reading position across document replacement (active: %s)",
  async (active) => {
    const bytes = new Uint8Array(Buffer.from(documentBase64, "base64"));
    const original = Object.assign(new Blob([bytes]), {
      arrayBuffer: async () => bytes.buffer,
    });
    let finish: (buffer: ArrayBuffer) => void = () => {};
    const replacement = Object.assign(new Blob([bytes]), {
      arrayBuffer: () =>
        new Promise<ArrayBuffer>((resolve) => {
          finish = resolve;
        }),
    });
    const props = { onError: jest.fn(), onScrollTopChange: jest.fn() };
    const { container, rerender } = render(
      <DocxDocumentPreview blob={original} {...props} />
    );
    const host = container.querySelector(".docx-host");
    const area = host?.parentElement;
    if (!area) throw new Error("Missing document scroll area");
    await waitFor(() =>
      expect(host?.shadowRoot?.textContent).toContain("Craft document preview")
    );
    fireEvent.scroll(area, { target: { scrollTop: 480 } });
    rerender(
      <DocxDocumentPreview blob={replacement} isActive={active} {...props} />
    );
    // Model the browser clamping the viewport while the document is empty.
    fireEvent.scroll(area, { target: { scrollTop: 0 } });
    expect(props.onScrollTopChange).toHaveBeenLastCalledWith(480);
    await act(async () => finish(bytes.buffer));
    await waitFor(() =>
      expect(host?.shadowRoot?.textContent).toContain("Craft document preview")
    );
    if (!active) {
      expect(area.scrollTop).toBe(0);
      rerender(<DocxDocumentPreview blob={replacement} isActive {...props} />);
    }
    expect(area.scrollTop).toBe(480);
  }
);
