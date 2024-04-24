import { useState } from "react";
import { FiChevronDown, FiChevronRight } from "react-icons/fi";

export function SectionHeader({
  children,
  includeMargin = true,
}: {
  children: string | JSX.Element;
  includeMargin?: boolean;
}) {
  return (
    <div
      className={"font-bold text-xl my-auto" + (includeMargin ? " mb-4" : "")}
    >
      {children}
    </div>
  );
}

export function HidableSection({
  children,
  sectionTitle,
  defaultHidden = false,
}: {
  children: string | JSX.Element;
  sectionTitle: string | JSX.Element;
  defaultHidden?: boolean;
}) {
  const [isHidden, setIsHidden] = useState(defaultHidden);

  return (
    <div>
      <div
        className="flex hover:bg-hover-light rounded cursor-pointer p-2"
        onClick={() => setIsHidden(!isHidden)}
      >
        <SectionHeader includeMargin={false}>{sectionTitle}</SectionHeader>
        <div className="my-auto ml-auto p-1">
          {isHidden ? (
            <FiChevronRight size={24} />
          ) : (
            <FiChevronDown size={24} />
          )}
        </div>
      </div>

      {!isHidden && <div className="mx-2 mt-2">{children}</div>}
    </div>
  );
}
