import { SourceIcon } from "@/components/SourceIcon";
import { AlertIcon } from "@/components/icons/icons";
import Link from "next/link";
import { SourceMetadata } from "@/lib/search/interfaces";
import React from "react";
import Text from "@/refresh-components/texts/Text";

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
              p-4
              rounded-lg
              w-40
              cursor-pointer
              shadow-md
              hover:bg-background-tint-02
              relative
              ${
                preSelect
                  ? "bg-background-tint-01 subtle-pulse"
                  : "bg-background-tint-00"
              }
            `}
      href={navigationUrl}
    >
      {sourceMetadata.federated && !hasExistingSlackCredentials && (
        <div className="absolute -top-2 -left-2 z-10 bg-background-tint-01 rounded-full p-1 shadow-md border border-status-warning-05">
          <AlertIcon size={18} className="text-status-warning-05" />
        </div>
      )}
      <SourceIcon sourceType={sourceMetadata.internalName} iconSize={24} />
      <Text className="pt-2">{sourceMetadata.displayName}</Text>
    </Link>
  );
}
