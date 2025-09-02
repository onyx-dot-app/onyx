import { SourceIcon } from "@/components/SourceIcon";
import { AlertIcon } from "@/components/icons/icons";
import Link from "next/link";
import { SourceMetadata } from "@/lib/search/interfaces";
import React from "react";

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
              hover:bg-background-settings-hover/50
              relative
              ${
                preSelect
                  ? "bg-background-settings-hover subtle-pulse"
                  : "bg-background-sidebar"
              }
            `}
      href={navigationUrl}
    >
      {sourceMetadata.federated && !hasExistingSlackCredentials && (
        <div className="absolute -top-2 -left-2 z-10 bg-white rounded-full p-1 shadow-md border border-orange-200">
          <AlertIcon size={18} className="text-orange-500 font-bold stroke-2" />
        </div>
      )}
      <SourceIcon sourceType={sourceMetadata.internalName} iconSize={24} />
      <p className="font-medium text-sm mt-2">{sourceMetadata.displayName}</p>
    </Link>
  );
}
