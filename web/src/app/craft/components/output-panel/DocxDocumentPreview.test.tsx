import { render, screen } from "@tests/setup/test-utils";
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
  const first = render(<DocxDocumentPreview blob={blob} onError={onError} />);
  expect(await screen.findByText("Craft document preview")).toBeInTheDocument();
  expect(onError).not.toHaveBeenCalled();
  first.unmount();
  render(<DocxDocumentPreview blob={blob} onError={onError} />);
  expect(screen.getByText("Craft document preview")).toBeInTheDocument();
  expect(screen.queryByText("Loading file")).not.toBeInTheDocument();
  expect(blob.arrayBuffer).toHaveBeenCalledTimes(1);
});
