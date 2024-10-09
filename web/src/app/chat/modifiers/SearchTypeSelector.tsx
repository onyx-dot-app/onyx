import { BasicClickable } from "@/components/BasicClickable";
import { ControlledPopup, DefaultDropdownElement } from "@/components/Dropdown";
import { useState } from "react";
import { FiCpu, FiSearch } from "react-icons/fi";

export const QA = "Question Answering";
export const SEARCH = "Search Only";

function SearchTypeSelectorContent({
  selectedSearchType,
  setSelectedSearchType,
}: {
  selectedSearchType: string;
  setSelectedSearchType: React.Dispatch<React.SetStateAction<string>>;
}) {
  return (
    <div className="w-56">
      <DefaultDropdownElement
        key={QA}
        name={QA}
        icon={FiCpu}
        onSelect={() => setSelectedSearchType(QA)}
        isSelected={selectedSearchType === QA}
      />
      <DefaultDropdownElement
        key={SEARCH}
        name={SEARCH}
        icon={FiSearch}
        onSelect={() => setSelectedSearchType(SEARCH)}
        isSelected={selectedSearchType === SEARCH}
      />
    </div>
  );
}

export function SearchTypeSelector({
  selectedSearchType,
  setSelectedSearchType,
}: {
  selectedSearchType: string;
  setSelectedSearchType: React.Dispatch<React.SetStateAction<string>>;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <ControlledPopup
      isOpen={isOpen}
      setIsOpen={setIsOpen}
      popupContent={
        <SearchTypeSelectorContent
          selectedSearchType={selectedSearchType}
          setSelectedSearchType={setSelectedSearchType}
        />
      }
    >
      <BasicClickable onClick={() => setIsOpen(!isOpen)}>
        <div className="flex text-xs">
          {selectedSearchType === QA ? (
            <>
              <FiCpu className="my-auto mr-1" /> QA
            </>
          ) : (
            <>
              <FiSearch className="my-auto mr-1" /> Search
            </>
          )}
        </div>
      </BasicClickable>
    </ControlledPopup>
  );
}
