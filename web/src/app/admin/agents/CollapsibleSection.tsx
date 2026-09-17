"use client";
import React, { ReactNode, useState } from "react";
import { FiSettings } from "react-icons/fi";
import { useTranslations } from "next-intl";
import { clickOnKeyDown } from "@opal/utils";

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
  const t = useTranslations("admin.agents");
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
        role="button"
        tabIndex={0}
        aria-expanded={!isCollapsed}
        aria-label={
          isCollapsed
            ? t("collapsibleSection.expand.ariaLabel")
            : t("collapsibleSection.collapse.ariaLabel")
        }
        onKeyDown={clickOnKeyDown(toggleCollapse)}
        className={`
          cursor-pointer
          ${isCollapsed ? "h-6" : "ps-6 border-s-2  border-border"}
        `}
        onClick={toggleCollapse}
      >
        {" "}
        {isCollapsed ? (
          <span className="collapse-toggle text-lg absolute start-0 top-0 text-sm flex items-center gap-x-3 cursor-pointer">
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
