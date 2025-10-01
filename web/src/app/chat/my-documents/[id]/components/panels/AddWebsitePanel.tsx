import React, { useState } from "react";
import { Link, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDocumentsContext } from "../../../DocumentsContext";

interface AddWebsitePanelProps {
  folderId: number;
  onCreateFileFromLink: (url: string, folderId: number) => Promise<void>;
}

export function AddWebsitePanel({
  folderId,
  onCreateFileFromLink,
}: AddWebsitePanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const { refreshFolderDetails } = useDocumentsContext();

  const handleCreateFileFromLink = async () => {
    if (!linkUrl) return;
    setIsCreating(true);
    try {
      await onCreateFileFromLink(linkUrl, folderId);
      setLinkUrl("");
      await refreshFolderDetails();
    } catch (error) {
      console.error("Error creating file from link:", error);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="p-4 border-b border-neutral-300 dark:border-neutral-600">
      <div
        className="flex items-center justify-between text-neutral-900 dark:text-neutral-300 cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded-md p-1"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center">
          <Link className="w-5 h-4 mr-3 text-neutral-600 dark:text-neutral-400" />
          <span className="text-sm font-medium leading-tight">
            Add a website
          </span>
        </div>
        <Button variant="ghost" size="sm" className="w-6 h-6 p-0 rounded-full">
          {isOpen ? (
            <ChevronDown className="w-[15px] h-3" />
          ) : (
            <ChevronRight className="w-[15px] h-3" />
          )}
        </Button>
      </div>

      {isOpen && (
        <div className="mt-3 mb-3 text-neutral-600 dark:text-neutral-400">
          <div className="flex mt-2 items-center">
            <input
              type="text"
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
              placeholder="Enter URL"
              className="flex-grow !text-sm mr-2 px-2 py-1 border border-neutral-300 dark:border-neutral-600 rounded bg-white dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100"
            />
            <Button
              variant="default"
              className="!text-sm"
              size="xs"
              onClick={handleCreateFileFromLink}
              disabled={isCreating || !linkUrl}
            >
              {isCreating ? "Creating..." : "Create"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
