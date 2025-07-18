import i18n from "@/i18n/init";
import k from "./../../../../../../i18n/keys";
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
          <span className="font-bold">{i18n.t(k.WARNING2)}</span>{" "}
          {i18n.t(k.THIS_FOLDER_IS_SHARED_ANY)}
        </p>
      </div>
    </div>
  );
};
