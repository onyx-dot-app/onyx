import { Citation } from "@/components/search/results/Citation";
import { WebResultIcon } from "@/components/WebResultIcon";
import { LoadedOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import { getSourceMetadata, SOURCE_METADATA_MAP } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import React, { memo } from "react";
import isEqual from "lodash/isEqual";
import { SlackIcon } from "@/components/icons/icons";
import { SourceIcon } from "@/components/SourceIcon";

export const MemoizedAnchor = memo(
  ({
    docs,
    updatePresentingDocument,
    children,
  }: {
    docs?: OnyxDocument[] | null;
    updatePresentingDocument: (doc: OnyxDocument) => void;
    children: React.ReactNode;
  }) => {
    const value = children?.toString();
    if (value?.startsWith("[") && value?.endsWith("]")) {
      const match = value.match(/\[(\d+)\]/);
      if (match) {
        const index = parseInt(match[1], 10) - 1;
        const associatedDoc = docs && docs[index];

        const url = associatedDoc?.link
          ? new URL(associatedDoc.link).origin + "/favicon.ico"
          : "";

        const icon =
          (associatedDoc && (
            <SourceIcon sourceType={associatedDoc?.source_type} iconSize={18} />
          )) ||
          null;

        return (
          <MemoizedLink
            updatePresentingDocument={updatePresentingDocument}
            document={{ ...associatedDoc, icon, url }}
          >
            {children}
          </MemoizedLink>
        );
      }
    }
    return (
      <MemoizedLink updatePresentingDocument={updatePresentingDocument}>
        {children}
      </MemoizedLink>
    );
  }
);

export const MemoizedLink = memo((props: any) => {
  const { node, document, updatePresentingDocument, ...rest } = props;
  const value = rest.children;

  if (value?.toString().startsWith("*")) {
    return (
      <div className="flex-none bg-background-800 inline-block rounded-full h-3 w-3 ml-2" />
    );
  } else if (value?.toString().startsWith("[")) {
    return (
      <Citation
        url={document?.url}
        icon={document?.icon as React.ReactNode}
        link={rest?.href}
        document={document as LoadedOnyxDocument}
        updatePresentingDocument={updatePresentingDocument}
      >
        {rest.children}
      </Citation>
    );
  }

  return (
    <a
      onMouseDown={() => rest.href && window.open(rest.href, "_blank")}
      className="cursor-pointer text-link hover:text-link-hover"
    >
      {rest.children}
    </a>
  );
});

export const MemoizedParagraph = memo(
  function MemoizedParagraph({ children }: any) {
    return <p className="text-default">{children}</p>;
  },
  (prevProps, nextProps) => {
    const areEqual = isEqual(prevProps.children, nextProps.children);
    return areEqual;
  }
);

MemoizedAnchor.displayName = "MemoizedAnchor";
MemoizedLink.displayName = "MemoizedLink";
MemoizedParagraph.displayName = "MemoizedParagraph";
