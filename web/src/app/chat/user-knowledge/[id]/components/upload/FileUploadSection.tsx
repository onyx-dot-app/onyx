import React, { useState, useRef } from "react";
import { Upload, Link, ArrowRight, X, Loader2 } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface FileUploadSectionProps {
  onUpload: (files: File[]) => void;
  onUrlUpload?: (url: string) => Promise<void>;
  disabledMessage?: string;
  disabled?: boolean;
  isUploading?: boolean;
  onUploadComplete?: () => void;
}

export const FileUploadSection: React.FC<FileUploadSectionProps> = ({
  onUpload,
  onUrlUpload,
  disabledMessage,
  disabled,
  isUploading = false,
  onUploadComplete,
}) => {
  const [uploadType, setUploadType] = useState<"file" | "url">("file");
  const [fileUrl, setFileUrl] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const dropAreaRef = useRef<HTMLLabelElement>(null);

  const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files);
      setSelectedFiles(newFiles);
      setIsProcessing(true);

      try {
        onUpload(newFiles);
        // Wait a bit to show loading state
        await new Promise((resolve) => setTimeout(resolve, 500));
      } finally {
        setIsProcessing(false);
        if (onUploadComplete) {
          onUploadComplete();
        }
      }

      e.target.value = ""; // Reset input after upload
    }
  };

  const handleUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFileUrl(e.target.value);
  };

  const handleUrlSubmit = async () => {
    if (fileUrl && onUrlUpload) {
      setIsProcessing(true);

      try {
        await onUrlUpload(fileUrl);
        setFileUrl("");
      } finally {
        setIsProcessing(false);
        if (onUploadComplete) {
          onUploadComplete();
        }
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && fileUrl) {
      handleUrlSubmit();
    }
  };

  // Drag and drop handlers
  const handleDragEnter = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) {
      setIsDragging(true);
      setUploadType("file"); // Switch to file mode when dragging
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled && !isDragging) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();

    // Only set isDragging to false if we're leaving the drop area itself, not its children
    if (
      !disabled &&
      dropAreaRef.current &&
      !dropAreaRef.current.contains(e.relatedTarget as Node)
    ) {
      setIsDragging(false);
    }
  };

  const handleDrop = async (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (!disabled && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const newFiles = Array.from(e.dataTransfer.files);
      setSelectedFiles(newFiles);
      setIsProcessing(true);

      try {
        onUpload(newFiles);
        // Wait a bit to show loading state
        await new Promise((resolve) => setTimeout(resolve, 500));
      } finally {
        setIsProcessing(false);
        if (onUploadComplete) {
          onUploadComplete();
        }
      }
    }
  };

  const isDisabled = disabled || isUploading || isProcessing;

  return (
    <TooltipProvider>
      <Tooltip delayDuration={0}>
        <TooltipTrigger className="mt-4 max-w-xl w-full">
          <div
            className={`border border-neutral-200 dark:border-neutral-700 bg-transparent rounded-lg p-3 shadow-sm ${
              !isDisabled && "hover:bg-neutral-50 dark:hover:bg-neutral-800"
            } transition-colors duration-200 ${
              isDisabled ? "cursor-not-allowed" : "cursor-pointer"
            }`}
          >
            <div className="flex flex-col gap-y-2">
              {/* Toggle Buttons */}
              <div className="flex bg-neutral-100 dark:bg-neutral-800 p-1 rounded-lg self-center mb-1">
                <button
                  type="button"
                  className={`px-3 py-1.5 rounded-md flex items-center justify-center gap-1.5 text-xs transition-all ${
                    uploadType === "file"
                      ? "bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-200 shadow-sm font-medium"
                      : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700"
                  }`}
                  onClick={() => setUploadType("file")}
                  disabled={isDisabled}
                >
                  <Upload className="w-3.5 h-3.5" />
                  <span>File</span>
                </button>
                <button
                  type="button"
                  className={`px-3 py-1.5 rounded-md flex items-center justify-center gap-1.5 text-xs transition-all ${
                    uploadType === "url"
                      ? "bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-200 shadow-sm font-medium"
                      : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700"
                  }`}
                  onClick={() => setUploadType("url")}
                  disabled={isDisabled}
                >
                  <Link className="w-3.5 h-3.5" />
                  <span>URL</span>
                </button>
              </div>

              {/* Content based on selected type */}
              {uploadType === "file" ? (
                <label
                  ref={dropAreaRef}
                  htmlFor="file-upload"
                  className={`w-full h-full block ${
                    isDisabled ? "pointer-events-none" : ""
                  } ${
                    isDragging
                      ? "border-2 border-dashed border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-900/20 rounded-md"
                      : ""
                  } transition-all duration-150 ease-in-out`}
                  onDragEnter={handleDragEnter}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                >
                  <div className="flex flex-col gap-y-1 items-center justify-between p-1">
                    <p className="text-center text-xs text-neutral-500 dark:text-neutral-400">
                      {isDragging
                        ? "Drop files here..."
                        : "Drag & drop or click to upload files"}
                    </p>
                    <Upload
                      className={`w-4 h-4 mt-1 ${
                        isDragging
                          ? "text-blue-500 dark:text-blue-400"
                          : "text-neutral-400 dark:text-neutral-500"
                      }`}
                    />
                  </div>
                  <input
                    disabled={isDisabled}
                    id="file-upload"
                    type="file"
                    multiple
                    className="hidden"
                    onChange={handleChange}
                  />
                </label>
              ) : (
                <div className="flex items-center gap-2 px-2">
                  <input
                    type="text"
                    placeholder="Enter website URL..."
                    className="w-full text-xs py-1.5 px-2 border border-neutral-200 dark:border-neutral-700 rounded-md bg-transparent focus:outline-none focus:ring-1 focus:ring-neutral-300 dark:focus:ring-neutral-600"
                    value={fileUrl}
                    onChange={handleUrlChange}
                    onKeyDown={handleKeyDown}
                    disabled={isDisabled}
                  />
                  <button
                    type="button"
                    onClick={handleUrlSubmit}
                    disabled={!fileUrl || isDisabled}
                    className={`p-1.5 rounded-md ${
                      !fileUrl || isDisabled
                        ? "text-neutral-400 cursor-not-allowed"
                        : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700"
                    }`}
                  >
                    {isUploading || isProcessing ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <ArrowRight className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
              )}
            </div>
          </div>
        </TooltipTrigger>
        {disabled ? <TooltipContent>{disabledMessage}</TooltipContent> : null}
      </Tooltip>
    </TooltipProvider>
  );
};
