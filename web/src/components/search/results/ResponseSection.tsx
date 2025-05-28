import { AlertIcon, TriangleAlertIcon } from "@/components/icons/icons";
import { useState } from "react";

export type StatusOptions = "in-progress" | "failed" | "warning" | "success";

interface ResponseSectionProps {
  header: JSX.Element | string;
  body: JSX.Element | string;
  status: StatusOptions;
  desiredOpenStatus: boolean;
  setDesiredOpenStatus?: (isOpen: boolean) => void;
  isNotControllable?: boolean;
}

export const ResponseSection = ({
  header,
  body,
  status,
  desiredOpenStatus,
  setDesiredOpenStatus,
  isNotControllable,
}: ResponseSectionProps) => {
  const [isOpen, setIsOpen] = useState<boolean | null>(null);

  let icon = null;
  if (status === "in-progress") {
    icon = <></>;
  }
  if (status === "failed") {
    icon = <AlertIcon size={16} className="text-red-500" />;
  }
  if (status === "success") {
    icon = <></>;
  }
  if (status === "warning") {
    icon = <TriangleAlertIcon size={16} className="text-yellow-600" />;
  }

  // use `desiredOpenStatus` if user has not clicked to open/close, otherwise use
  // `isOpen` state
  const finalIsOpen = isOpen !== null ? isOpen : desiredOpenStatus;
  return (
    <div>
      <div
        className={`
        flex 
        my-1 
        p-1 
        rounded  
        select-none 
        ${isNotControllable ? "" : "hover:bg-background-800 cursor-pointer"}`}
        onClick={() => {
          if (!isNotControllable) {
            if (isOpen === null) {
              setIsOpen(!desiredOpenStatus);
            } else {
              setIsOpen(!isOpen);
            }
          }
          if (setDesiredOpenStatus) {
            setDesiredOpenStatus(!desiredOpenStatus);
          }
        }}
      >
        <div className="my-auto">{icon}</div>
        <div className="my-auto text-sm text-text-200">{header}</div>
      </div>
      {finalIsOpen && <div className="pb-1 mx-2 text-sm mb-1">{body}</div>}
    </div>
  );
};
