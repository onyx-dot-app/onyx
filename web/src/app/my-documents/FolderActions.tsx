import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Plus, Upload, RefreshCw } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface FolderActionsProps {
  onRefresh: () => void;
  onCreateFolder: (folderName: string) => void;
  onUploadFiles: (files: FileList) => void;
}

export function FolderActions({
  onRefresh,
  onCreateFolder,
  onUploadFiles,
}: FolderActionsProps) {
  const [newFolderName, setNewFolderName] = useState("");
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);

  const handleCreateFolder = () => {
    if (newFolderName.trim()) {
      onCreateFolder(newFolderName.trim());
      setNewFolderName("");
      setIsCreatingFolder(false);
    }
  };

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files) {
      onUploadFiles(files);
    }
  };

  return (
    <div className="flex items-center space-x-2">
      <Button
        onClick={onRefresh}
        variant="outline"
        size="sm"
        className="border-background-300 hover:bg-background-100"
      >
        <RefreshCw className="h-4 w-4 text-text-600" />
      </Button>
      <Popover open={isCreatingFolder} onOpenChange={setIsCreatingFolder}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="border-background-300 hover:bg-background-100"
          >
            <Plus className="h-4 w-4 text-text-600" />
          </Button>
        </PopoverTrigger>
        {isCreatingFolder && (
          <PopoverContent className="w-56 p-3 bg-white shadow-md rounded-md">
            <div className="space-y-2 flex flex-col">
              <Input
                type="text"
                placeholder="New folder name"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                className="!w-full p-1 flex text-sm border border-background-300 focus:border-background-500 rounded"
              />
              <div className="flex justify-between space-x-2">
                <Button
                  onClick={handleCreateFolder}
                  size="sm"
                  className="bg-background-800 hover:bg-background-900 text-white text-xs"
                >
                  Create
                </Button>
                <Button
                  onClick={() => setIsCreatingFolder(false)}
                  variant="outline"
                  size="sm"
                  className="border border-background-300 hover:bg-background-100 text-xs"
                >
                  Cancel
                </Button>
              </div>
            </div>
          </PopoverContent>
        )}
      </Popover>
      <Button
        variant="outline"
        size="sm"
        className="border-background-300 hover:bg-background-100"
        onClick={() => document.getElementById("file-upload")?.click()}
      >
        <Upload className="h-4 w-4 text-text-600" />
      </Button>
      <input
        id="file-upload"
        type="file"
        multiple
        onChange={handleFileUpload}
        className="hidden"
      />
    </div>
  );
}
