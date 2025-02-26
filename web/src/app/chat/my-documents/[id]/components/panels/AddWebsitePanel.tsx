import React, { useState } from "react";
import { Link, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

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

  const handleCreateFileFromLink = async () => {
    if (!linkUrl) return;
    setIsCreating(true);
    try {
      await onCreateFileFromLink(linkUrl, folderId);
      setLinkUrl("");
    } catch (error) {
      console.error("Error creating file from link:", error);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="p-4 border-b border-neutral-200 dark:border-neutral-700">
      <div
        className="flex items-center justify-between w-full cursor-pointer text-[#13343a] dark:text-neutral-300"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center">
          <Link className="w-5 h-4 mr-3" />
          <span className="text-sm font-medium leading-tight">
            Add a website
          </span>
        </div>
        <Button variant="ghost" size="icon" className="w-6 h-6 p-0">
          {isOpen ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </Button>
      </div>

      {isOpen && (
        <div className="flex mt-4 items-center">
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
      )}
    </div>
  );
}
