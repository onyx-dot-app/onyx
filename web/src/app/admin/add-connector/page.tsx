"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import { SourceIcon } from "@/components/SourceIcon";
import { AdminPageTitle } from "@/components/admin/Title";
import { ConnectorIcon } from "@/components/icons/icons";
import { SourceCategory, SourceMetadata } from "@/lib/search/interfaces";
import { listSourceMetadata } from "@/lib/sources";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

function SourceTile({
  sourceMetadata,
  preSelect,
}: {
  sourceMetadata: SourceMetadata;
  preSelect?: boolean;
}) {
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
        hover:bg-accent-background-hovered
        ${
          preSelect
            ? "bg-accent-background-hovered subtle-pulse"
            : "bg-accent-background"
        }
      `}
      href={sourceMetadata.adminUrl}
    >
      <SourceIcon sourceType={sourceMetadata.internalName} iconSize={24} />
      <p className="font-medium text-sm mt-2">{sourceMetadata.displayName}</p>
    </Link>
  );
}
export default function Page() {
  const sources = useMemo(() => listSourceMetadata(), []);
  const [searchTerm, setSearchTerm] = useState("");

  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, []);
  const filterSources = useCallback(
    (sources: SourceMetadata[]) => {
      if (!searchTerm) return sources;
      const lowerSearchTerm = searchTerm.toLowerCase();
      return sources.filter(
        (source) =>
          source.displayName.toLowerCase().includes(lowerSearchTerm) ||
          source.category.toLowerCase().includes(lowerSearchTerm)
      );
    },
    [searchTerm]
  );

  const categorizedSources = useMemo(() => {
    const filtered = filterSources(sources);
    return Object.values(SourceCategory).reduce((acc, category) => {
      acc[category] = sources.filter(
        (source) =>
          source.category === category &&
          (filtered.includes(source) ||
            category.toLowerCase().includes(searchTerm.toLowerCase()))
      );
      return acc;
    }, {} as Record<SourceCategory, SourceMetadata[]>);
  }, [sources, filterSources, searchTerm]);

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      const filteredCategories = Object.entries(categorizedSources).filter(
        ([_, sources]) => sources.length > 0
      );
      if (
        filteredCategories.length > 0 &&
        filteredCategories[0][1].length > 0
      ) {
        const firstSource = filteredCategories[0][1][0];
        if (firstSource) {
          window.open(firstSource.adminUrl, "_self");
        }
      }
    }
  };

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<ConnectorIcon size={32} />}
        title={i18n.t(k.ADD_CONNECTOR)}
        farRightElement={
          <Link href="/admin/indexing/status">
            <Button variant="success-reverse">
              {i18n.t(k.SEE_CONNECTORS)}
            </Button>
          </Link>
        }
      />

      <input
        type="text"
        ref={searchInputRef}
        placeholder={i18n.t(k.SEARCH_CONNECTORS_PLACEHOLDER)}
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        onKeyDown={handleKeyPress}
        className="ml-1 w-96 h-9  flex-none rounded-md border border-border bg-background-50 px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />

      {Object.entries(categorizedSources)
        .filter(([_, sources]) => sources.length > 0)
        .map(([category, sources], categoryInd) => (
          <div key={category} className="mb-8">
            <div className="flex mt-8">
              <Title>{category}</Title>
            </div>
            {/* <p>{getCategoryDescription(category as SourceCategory)}</p> */}
            <div className="flex flex-wrap gap-4 p-4">
              {sources.map((source, sourceInd) => (
                <SourceTile
                  preSelect={
                    searchTerm.length > 0 && categoryInd == 0 && sourceInd == 0
                  }
                  key={source.internalName}
                  sourceMetadata={source}
                />
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}

// function getCategoryDescription(category: SourceCategory): string {
//   switch (category) {
//     case SourceCategory.Messaging:
//       return "Integration with messaging platforms and communication tools.";
//     case SourceCategory.ProjectManagement:
//       return "Link to project management tools and task tracking systems.";
//     case SourceCategory.CustomerSupport:
//       return "Connect to customer support systems and help desk services.";
//     case SourceCategory.CodeRepository:
//       return "Integration with code repositories and version control systems.";
//     case SourceCategory.Storage:
//       return "Connect to cloud storage and file hosting services.";
//     case SourceCategory.Wiki:
//       return "Link to wiki platforms and knowledge bases.";
//     case SourceCategory.Other:
//       return "Connect to other various knowledge sources.";
//     default:
//       return "Connect to various knowledge sources.";
//   }
// }
