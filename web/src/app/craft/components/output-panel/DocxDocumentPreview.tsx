"use client";

import { useLayoutEffect, useEffectEvent, useRef, useState } from "react";
import { FilePreviewLoading } from "@/app/craft/components/output-panel/FilePreviewLoading";
import { renderDocx } from "@/lib/docx/renderDocx";
import {
  FilePreviewScrollArea,
  type FilePreviewScrollPosition,
} from "@/app/craft/components/output-panel/FilePreviewScrollArea";

// Entries expire with the preview's cached blob.
const renderedDocuments = new WeakMap<
  Blob,
  Awaited<ReturnType<typeof renderDocx>>
>();

interface DocxDocumentPreviewProps extends FilePreviewScrollPosition {
  blob: Blob;
  onError: () => void;
}

export default function DocxDocumentPreview({
  blob,
  onError,
  ...scroll
}: DocxDocumentPreviewProps) {
  const host = useRef<HTMLDivElement>(null);
  const reportError = useEffectEvent(onError);
  const [loaded, setLoaded] = useState<Blob>();
  useLayoutEffect(() => {
    let cancelled = false;
    if (!host.current) return;
    const root =
      host.current.shadowRoot ?? host.current.attachShadow({ mode: "open" });
    function display({ body, styles }: Awaited<ReturnType<typeof renderDocx>>) {
      root.replaceChildren(styles.cloneNode(true), body.cloneNode(true));
      setLoaded(blob);
    }
    const cached = renderedDocuments.get(blob);
    if (cached) {
      display(cached);
      return;
    }
    root.replaceChildren();
    void blob
      .arrayBuffer()
      .then(renderDocx)
      .then((document) => {
        renderedDocuments.set(blob, document);
        if (!cancelled) display(document);
      })
      .catch(() => {
        if (!cancelled) reportError();
      });
    return () => {
      cancelled = true;
    };
  }, [blob]);
  return (
    <FilePreviewScrollArea {...scroll} contentReady={loaded === blob}>
      {loaded !== blob && <FilePreviewLoading />}
      <div ref={host} className="docx-host" />
    </FilePreviewScrollArea>
  );
}
