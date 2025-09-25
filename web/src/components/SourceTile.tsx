import { SourceIcon } from "@/components/SourceIcon";
import { AlertIcon } from "@/components/icons/icons";
import Link from "next/link";
import { SourceMetadata } from "@/lib/search/interfaces";
import React from "react";
import Text from "@/components-2/Text";

interface SourceTileProps {
  sourceMetadata: SourceMetadata;
  preSelect?: boolean;
  navigationUrl: string;
  hasExistingSlackCredentials: boolean;
}

export default function SourceTile({
  sourceMetadata,
  preSelect,
  navigationUrl,
  hasExistingSlackCredentials,
}: SourceTileProps) {
  return (
    <Link
      className={`flex
              flex-col
              items-center
              justify-center
              p-spacing-paragraph
              rounded-lg
              w-40
              cursor-pointer
              shadow-md
              relative
              ${preSelect ? "bg-background-tint-03 subtle-pulse" : "bg-background-tint-02"}
              hover:bg-background-tint-03
              gap-padding-button
            `}
      href={navigationUrl}
    >
      {sourceMetadata.federated && !hasExistingSlackCredentials && (
        <div className="absolute -top-2 -left-2 z-10 bg-background-neutral-inverted-00 rounded-full p-1 shadow-md border border-status-warning-02">
          <AlertIcon
            size={18}
            className="text-status-warning-05 font-bold stroke-2"
          />
        </div>
      )}
      <SourceIcon sourceType={sourceMetadata.internalName} iconSize={24} />
      <Text>{sourceMetadata.displayName}</Text>
    </Link>
  );
}
