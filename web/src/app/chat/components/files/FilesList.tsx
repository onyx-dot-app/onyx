"use client";

import React, { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  FileIcon,
  Globe,
  Image as ImageIcon,
  FileText,
  Search,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ProjectFile } from "../../projects/ProjectsContext";

interface FilesListProps {
  className?: string;
  recentFiles: ProjectFile[];
  onPickRecent?: (file: ProjectFile) => void;
}

const kindIcon = (kind: string, status?: string) => {
  if (String(status).toLowerCase() === "processing") {
    return <Loader2 className="h-4 w-4 animate-spin" />;
  }
  const normalized = kind.toLowerCase();
  if (normalized.includes("url") || normalized.includes("site"))
    return <Globe className="h-4 w-4" />;
  if (
    normalized.includes("image") ||
    normalized.includes("png") ||
    normalized.includes("jpg")
  )
    return <ImageIcon className="h-4 w-4" />;
  if (normalized.includes("txt") || normalized.includes("text"))
    return <FileText className="h-4 w-4" />;
  return <FileIcon className="h-4 w-4" />;
};

export default function FilesList({
  className,
  recentFiles,
  onPickRecent,
}: FilesListProps) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return recentFiles;
    return recentFiles.filter((f) => f.name.toLowerCase().includes(s));
  }, [recentFiles, search]);

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search files..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 pl-8"
          removeFocusRing
        />
      </div>
      <Separator />
      <ScrollArea className="h-[320px] pr-2">
        <div className="flex flex-col">
          {filtered.map((f) => (
            <button
              key={f.id}
              className={cn(
                "flex items-center justify-between gap-3 text-left rounded-md px-2 py-2",
                "hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50"
              )}
              onClick={() => onPickRecent && onPickRecent(f)}
            >
              <div className="flex items-center gap-3 min-w-0">
                {kindIcon(f.file_type, (f as any).status)}
                <div className="min-w-0">
                  <div className="truncate text-sm font-normal">{f.name}</div>
                  <div className="text-xs text-text-400 dark:text-neutral-400">
                    {f.status
                      ? String(f.status).toLowerCase() === "processing"
                        ? "Processing..."
                        : f.status
                      : f.file_type}
                  </div>
                </div>
              </div>
              {f.last_accessed_at && (
                <div className="text-xs text-text-400 dark:text-neutral-400 whitespace-nowrap ml-3">
                  {f.last_accessed_at}
                </div>
              )}
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="text-sm text-muted-foreground px-2 py-4">
              No files found.
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
