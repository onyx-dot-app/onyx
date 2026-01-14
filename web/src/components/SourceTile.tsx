import { SourceIcon } from "@/components/SourceIcon";
import Link from "next/link";
import type { Route } from "next";
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
      href={navigationUrl as Route}
    >
      <SourceIcon sourceType={sourceMetadata.internalName} iconSize={24} />
      <Text as="p" className="pt-2">
        {sourceMetadata.displayName}
      </Text>
    </Link>
  );
}
