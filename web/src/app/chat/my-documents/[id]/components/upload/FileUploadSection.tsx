import React, { useState, useRef, useEffect } from "react";
import { Upload, Link, X, Loader2, Plus, AlertCircle } from "lucide-react";
import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// Define allowed file extensions
const ALLOWED_FILE_TYPES = [
  // Documents
  ".pdf",
  ".doc",
  ".docx",
  ".txt",
  ".rtf",
  ".odt",
  // Spreadsheets
  ".csv",
  ".xls",
  ".xlsx",
  ".ods",
  // Presentations
  ".ppt",
  ".pptx",
  ".odp",
  // Images
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".bmp",
  ".svg",
  ".webp",
  // Web
  ".html",
  ".htm",
  ".xml",
  ".json",
  ".md",
  ".markdown",
  // Archives (if supported by your system)
  ".zip",
  ".rar",
  ".7z",
  ".tar",
  ".gz",
  // Code
  ".js",
  ".jsx",
  ".ts",
  ".tsx",
  ".py",
  ".java",
  ".c",
  ".cpp",
  ".cs",
  ".php",
  ".rb",
  ".go",
  ".swift",
  ".html",
  ".css",
  ".scss",
  ".sass",
  ".less",
];

interface FileUploadSectionProps {
  onUpload: (files: File[]) => void;
  onUrlUpload?: (url: string) => Promise<void>;
  disabledMessage?: string;
  disabled?: boolean;
  isUploading?: boolean;
  onUploadComplete?: () => void;
  onUploadProgress?: (fileName: string, progress: number) => void;
}

export const FileUploadSection: React.FC<FileUploadSectionProps> = ({
  onUpload,
  onUrlUpload,
  disabledMessage,
  disabled,
  isUploading = false,
  onUploadComplete,
  onUploadProgress,
}) => {
  const [uploadType, setUploadType] = useState<"file" | "url">("file");
  const [fileUrl, setFileUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [invalidFiles, setInvalidFiles] = useState<string[]>([]);
  const [showInvalidFileMessage, setShowInvalidFileMessage] = useState(false);
  const dropAreaRef = useRef<HTMLLabelElement>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Focus URL input when switching to URL mode
  useEffect(() => {
    if (uploadType === "url" && urlInputRef.current) {
      urlInputRef.current.focus();
    }
  }, [uploadType]);

  // Hide invalid file message after 5 seconds
  useEffect(() => {
    if (showInvalidFileMessage) {
      // Remove the auto-hide timer
      return () => {};
    }
  }, [showInvalidFileMessage]);

  // Function to check if a file type is allowed
  const isFileTypeAllowed = (file: File): boolean => {
    const fileName = file.name.toLowerCase();
    const fileExtension = fileName.substring(fileName.lastIndexOf("."));
    return ALLOWED_FILE_TYPES.includes(fileExtension);
  };

  // Filter files to only include allowed types
  const filterAllowedFiles = (
    files: File[]
  ): { allowed: File[]; rejected: string[] } => {
    const allowed: File[] = [];
    const rejected: string[] = [];

    files.forEach((file) => {
      if (isFileTypeAllowed(file)) {
        allowed.push(file);
      } else {
        rejected.push(file.name);
      }
    });

    return { allowed, rejected };
  };

  const simulateFileUploadProgress = (file: File) => {
    let progress = 0;
    const fileSize = file.size;

    // Calculate simulation parameters based on file size
    const getUploadParameters = (size: number) => {
      // For very small files, upload is faster
      if (size < 100 * 1024) {
        // < 100KB
        return {
          initialJump: 40, // Quick initial progress jump
          steadyRate: 10, // Steady upload rate (percentage points per second)
          finalSlowdown: 0.5, // Slower rate near completion
          totalTime: 2000, // Total upload time in ms
        };
      }
      // For medium files
      else if (size < 1024 * 1024) {
        // < 1MB
        return {
          initialJump: 30,
          steadyRate: 7,
          finalSlowdown: 0.3,
          totalTime: 4000,
        };
      }
      // For larger files
      else if (size < 10 * 1024 * 1024) {
        // < 10MB
        return {
          initialJump: 20,
          steadyRate: 5,
          finalSlowdown: 0.2,
          totalTime: 8000,
        };
      }
      // For very large files
      else {
        return {
          initialJump: 10,
          steadyRate: 3,
          finalSlowdown: 0.1,
          totalTime: 15000,
        };
      }
    };

    const params = getUploadParameters(fileSize);

    // Initial jump to show immediate progress
    setTimeout(() => {
      progress = params.initialJump;
      if (onUploadProgress) {
        onUploadProgress(file.name, progress);
      }
    }, 100);

    // Middle section - steady progress
    const steadyUpdateInterval = 300; // ms between updates
    const steadyIncrement = params.steadyRate * (steadyUpdateInterval / 1000);
    const steadySteps = Math.floor((90 - params.initialJump) / steadyIncrement);

    // Start steady updates after initial jump
    let steadyTimer = setTimeout(() => {
      let step = 0;
      const intervalId = setInterval(() => {
        step++;
        progress = Math.min(params.initialJump + step * steadyIncrement, 90);

        if (onUploadProgress) {
          onUploadProgress(file.name, Math.round(progress));
        }

        if (step >= steadySteps) {
          clearInterval(intervalId);

          // Final slowdown phase - more gradual progress to 99%
          const finalUpdateInterval = 400;
          const finalIncrement = params.finalSlowdown;
          let finalProgress = progress;

          const finalIntervalId = setInterval(() => {
            finalProgress += finalIncrement;
            if (finalProgress >= 99) {
              finalProgress = 99;
              clearInterval(finalIntervalId);
            }

            if (onUploadProgress) {
              onUploadProgress(file.name, Math.round(finalProgress));
            }
          }, finalUpdateInterval);
        }
      }, steadyUpdateInterval);
    }, 300);

    // Ensure we eventually reach 100% after the expected total time
    setTimeout(() => {
      if (onUploadProgress) {
        // Send 99% if we haven't reached it yet
        onUploadProgress(file.name, 99);

        // After a short pause, mark as complete
        setTimeout(() => {
          onUploadProgress(file.name, 100);
        }, 500);
      }
    }, params.totalTime);
  };

  const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files);
      const { allowed, rejected } = filterAllowedFiles(newFiles);
      setSelectedFiles(allowed);

      // Show error message if there are invalid files
      if (rejected.length > 0) {
        setInvalidFiles(rejected);
        setShowInvalidFileMessage(true);
      }

      // Only proceed if there are valid files
      if (allowed.length > 0) {
        setIsProcessing(true);

        try {
          // Start progress tracking for each file
          allowed.forEach((file) => {
            simulateFileUploadProgress(file);
          });

          onUpload(allowed);

          // Wait a bit to show loading state
          await new Promise((resolve) => setTimeout(resolve, 500));
        } finally {
          setIsProcessing(false);
          if (onUploadComplete) {
            onUploadComplete();
          }
        }
      }

      e.target.value = ""; // Reset input after upload
    }
  };

  const validateUrl = (url: string): boolean => {
    try {
      // Check if URL is valid format
      const urlObj = new URL(url);
      // Make sure it has http or https protocol
      return urlObj.protocol === "http:" || urlObj.protocol === "https:";
    } catch (e) {
      return false;
    }
  };

  const handleUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const url = e.target.value;
    setFileUrl(url);

    // Clear error when input changes
    if (urlError) {
      setUrlError(null);
    }
  };

  const handleUrlSubmit = async () => {
    if (!fileUrl) return;

    if (!validateUrl(fileUrl)) {
      setUrlError("Please enter a valid URL (e.g., https://example.com)");
      return;
    }

    if (onUrlUpload) {
      setIsProcessing(true);

      try {
        // Simulate progress for URL uploads
        let progress = 0;
        const progressInterval = setInterval(() => {
          progress += 10;
          if (progress >= 95) {
            clearInterval(progressInterval);
          }
          if (onUploadProgress) {
            onUploadProgress(fileUrl, progress);
          }
        }, 300);

        await onUrlUpload(fileUrl);

        // Set to 100% when complete
        if (onUploadProgress) {
          onUploadProgress(fileUrl, 100);
        }

        clearInterval(progressInterval);
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
      const { allowed, rejected } = filterAllowedFiles(newFiles);
      setSelectedFiles(allowed);

      // Show error message if there are invalid files
      if (rejected.length > 0) {
        setInvalidFiles(rejected);
        setShowInvalidFileMessage(true);
      }

      // Only proceed if there are valid files
      if (allowed.length > 0) {
        setIsProcessing(true);

        try {
          // Start progress tracking for each file
          allowed.forEach((file) => {
            simulateFileUploadProgress(file);
          });

          onUpload(allowed);

          // Wait a bit to show loading state
          await new Promise((resolve) => setTimeout(resolve, 500));
        } finally {
          setIsProcessing(false);
          if (onUploadComplete) {
            onUploadComplete();
          }
        }
      }
    }
  };

  return (
    <div className="mt-4 max-w-xl w-full">
      {/* Invalid file message */}
      {showInvalidFileMessage && invalidFiles.length > 0 && (
        <div className="mb-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-md text-yellow-800 dark:text-yellow-200 text-sm flex items-start">
          <AlertCircle className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium">
              Unsupported file type{invalidFiles.length > 1 ? "s" : ""}
            </p>
            <p className="mt-1">
              {invalidFiles.length > 1
                ? `The following files cannot be uploaded: ${invalidFiles
                    .slice(0, 3)
                    .join(", ")}${
                    invalidFiles.length > 3
                      ? ` and ${invalidFiles.length - 3} more`
                      : ""
                  }`
                : `The file "${invalidFiles[0]}" cannot be uploaded.`}
            </p>
          </div>
          <button
            onClick={() => setShowInvalidFileMessage(false)}
            className="flex-shrink-0 text-yellow-700 dark:text-yellow-300 hover:text-yellow-900 dark:hover:text-yellow-100"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Toggle Buttons - Now outside the main container */}

      {/* Main upload area */}
      <TooltipProvider>
        <Tooltip delayDuration={0}>
          <TooltipTrigger
            className={`w-full ${uploadType === "url" ? "cursor-default" : ""}`}
          >
            <div
              className={`border  bg-transparent border-neutral-200 dark:border-neutral-700 bg- rounded-lg  shadow-sm 
                ${
                  uploadType === "file" &&
                  "hover:bg-neutral-50 dark:hover:bg-neutral-800"
                } transition-colors duration-200 
                ${uploadType === "file" ? "cursor-pointer" : "cursor-default"}
                 h-[160px] flex items-center justify-center`}
            >
              {/* Common layout structure for both modes */}
              <div className="w-full h-full flex flex-col items-center">
                {uploadType === "file" ? (
                  <label
                    ref={dropAreaRef}
                    htmlFor="file-upload"
                    className={`w-full p-4  h-full cursor-pointer flex flex-col items-center justify-center ${
                      isDragging
                        ? "border-2 border-dashed border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-900/20 rounded-md"
                        : ""
                    } transition-all duration-150 ease-in-out`}
                    onDragEnter={handleDragEnter}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                  >
                    {/* Icon container - fixed position for both modes */}
                    <div className="h-[40px] flex items-center justify-center">
                      <Upload
                        className={`w-6 h-6 ${
                          isDragging
                            ? "text-blue-500 dark:text-blue-400"
                            : "text-neutral-400 dark:text-neutral-500"
                        }`}
                      />
                    </div>
                    <div className="mt-2">
                      <p className="text-center text-sm text-neutral-500 dark:text-neutral-400">
                        {isDragging
                          ? "Drop files here..."
                          : "Drag & drop or click to upload files"}
                      </p>
                    </div>
                    <input
                      id="file-upload"
                      type="file"
                      multiple
                      className="hidden"
                      onChange={handleChange}
                    />
                  </label>
                ) : (
                  <>
                    {/* Icon container - fixed position for both modes */}
                    <div className="h-[40px] flex items-center justify-center mt-6">
                      <Link className="w-6 h-6 text-neutral-400 dark:text-neutral-500" />
                    </div>

                    {/* Content area - different for each mode but with consistent spacing */}
                    <div className="flex-1 w-full flex flex-col items-center justify-center mt-2">
                      <div className="flex items-center gap-2 w-full  px-4 max-w-md">
                        <input
                          ref={urlInputRef}
                          type="text"
                          placeholder="Enter website URL..."
                          className={`w-full text-sm py-2 px-3 border rounded-md bg-transparent focus:outline-none focus:ring-1 
                            ${
                              urlError
                                ? "border-red-400 dark:border-red-600 focus:ring-red-400 dark:focus:ring-red-600"
                                : "border-neutral-200 dark:border-neutral-700 focus:ring-neutral-300 dark:focus:ring-neutral-600"
                            }`}
                          value={fileUrl}
                          onChange={handleUrlChange}
                          onKeyDown={handleKeyDown}
                        />
                        <button
                          type="button"
                          onClick={handleUrlSubmit}
                          disabled={!fileUrl || isProcessing}
                          className={`p-2 rounded-md ${
                            !fileUrl || isProcessing
                              ? "text-neutral-400 cursor-not-allowed"
                              : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700"
                          }`}
                        >
                          {isProcessing ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Plus className="w-4 h-4" />
                          )}
                        </button>
                      </div>
                      {urlError && (
                        <p className="text-red-500 dark:text-red-400 text-xs mt-1 max-w-md px-1">
                          {urlError}
                        </p>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </TooltipTrigger>
        </Tooltip>
      </TooltipProvider>
      <div className="flex bg-neutral-100 dark:bg-neutral-800 p-1 rounded-lg self-center mt-2 w-fit mx-auto">
        <button
          type="button"
          className={`px-3 py-1.5 rounded-md flex items-center justify-center gap-1.5 text-xs transition-all ${
            uploadType === "file"
              ? "bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-200 shadow-sm font-medium"
              : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700"
          }`}
          onClick={() => setUploadType("file")}
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
        >
          <Link className="w-3.5 h-3.5" />
          <span>URL</span>
        </button>
      </div>
    </div>
  );
};
