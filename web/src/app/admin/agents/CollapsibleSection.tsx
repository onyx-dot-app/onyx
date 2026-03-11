"use client";
import React, { ReactNode, useState } from "react";
import { FiSettings } from "react-icons/fi";

interface CollapsibleSectionProps {
  children: ReactNode;
  prompt?: string;
  className?: string;
}

const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
  children,
  prompt,
  className = "",
}) => {
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);

  const toggleCollapse = (e?: React.MouseEvent<HTMLDivElement>) => {
    // Only toggle if the click is on the border or plus sign
    if (
      !e ||
      e.currentTarget === e.target ||
      (e.target as HTMLElement).classList.contains("collapse-toggle")
    ) {
      setIsCollapsed(!isCollapsed);
    }
  };

  return (
    <div
      className={`relative ${isCollapsed ? "h-6" : ""} ${className}`}
      style={{ transition: "height 0.3s ease-out" }}
    >
      <div
        className={`
          cursor-pointer
          ${isCollapsed ? "h-6" : "pl-6 border-l-2  border-border"}
        `}
        onClick={toggleCollapse}
      >
        {" "}
        {isCollapsed ? (
          <span className="collapse-toggle text-lg absolute left-0 top-0 text-sm flex items-center gap-x-3 cursor-pointer">
            <FiSettings className="pointer-events-none my-auto" size={16} />
            {prompt}{" "}
          </span>
        ) : (
          <>{children}</>
        )}
      </div>
    </div>
  );
};

export default CollapsibleSection;
