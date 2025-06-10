import React from "react";
import { AlertTriangle } from "lucide-react";

interface UploadWarningProps {
  className?: string;
}

export const UploadWarning: React.FC<UploadWarningProps> = ({ className }) => {
  return (
    <div
      className={`bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-4 ${
        className || ""
      }`}
    >
      <div className="flex items-center">
        <AlertTriangle className="h-6 w-6 mr-2" />
        <p>
          <span className="font-bold">Warning:</span> This folder is shared. Any
          documents you upload will be accessible to the shared assistants.
        </p>
      </div>
    </div>
  );
};
