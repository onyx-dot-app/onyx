import React from "react";
import { Upload } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
interface FileUploadSectionProps {
  onUpload: (files: File[]) => void;
  disabledMessage?: string;
  disabled?: boolean;
}

export const FileUploadSection: React.FC<FileUploadSectionProps> = ({
  onUpload,
  disabledMessage,
  disabled,
}) => {
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files);
      onUpload(newFiles);
    }
  };

  return (
    <TooltipProvider>
      <Tooltip delayDuration={0}>
        <TooltipTrigger className="mt-6 w-full">
          <div
            className={`border border-neutral-200 dark:border-neutral-700 bg-transparent rounded-lg p-4 shadow-sm ${
              !disabled && "hover:bg-neutral-50 dark:hover:bg-neutral-800"
            } transition-colors duration-200 ${
              disabled ? "cursor-not-allowed" : "cursor-pointer"
            }`}
          >
            <label
              htmlFor="file-upload"
              className={`w-full h-full block ${
                disabled ? "pointer-events-none" : ""
              }`}
            >
              <div className="flex flex-col gap-y-2 items-center justify-between">
                <p className="flex flex-col text-center text-sm text-neutral-500 dark:text-neutral-400">
                  Add files to this project
                </p>
                <Upload className="w-5 h-5 text-neutral-400 dark:text-neutral-500" />
              </div>
              <input
                disabled={disabled}
                id="file-upload"
                type="file"
                multiple
                className="hidden"
                onChange={handleChange}
              />
            </label>
          </div>
        </TooltipTrigger>
        {disabled ? <TooltipContent>{disabledMessage}</TooltipContent> : null}
      </Tooltip>
    </TooltipProvider>
  );
};
