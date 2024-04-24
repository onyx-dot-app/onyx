import { DocumentSet, ValidSources } from "@/lib/types";
import { CustomCheckbox } from "../CustomCheckbox";
import { SourceIcon } from "../SourceIcon";

export function DocumentSetSelectable({
  documentSet,
  isSelected,
  onSelect,
}: {
  documentSet: DocumentSet;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const uniqueSources = new Set<ValidSources>();
  documentSet.cc_pair_descriptors.forEach((ccPairDescriptor) => {
    uniqueSources.add(ccPairDescriptor.connector.source);
  });

  return (
    <div
      key={documentSet.id}
      className={
        `
        w-72
        px-3 
        py-1
        rounded-lg 
        border
        border-border
        flex 
        cursor-pointer ` +
        (isSelected ? " bg-hover" : " bg-background hover:bg-hover-light")
      }
      onClick={onSelect}
    >
      <div className="flex w-full">
        <div className="flex flex-col h-full">
          <div className="font-bold">{documentSet.name}</div>
          <div className="text-xs">{documentSet.description}</div>
          <div className="flex gap-x-2 pt-1 mt-auto mb-1">
            {Array.from(uniqueSources).map((source) => (
              <SourceIcon key={source} sourceType={source} iconSize={16} />
            ))}
          </div>
        </div>
        <div className="ml-auto my-auto">
          <div className="pl-1">
            <CustomCheckbox checked={isSelected} onChange={() => null} />
          </div>
        </div>
      </div>
    </div>
  );
}
