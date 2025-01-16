import { CustomTooltip } from "@/components/tooltip/CustomTooltip";
import { FiBook } from "react-icons/fi";

export function SkippedSearch({
  handleForceSearch,
}: {
  handleForceSearch: () => void;
}) {
  return (
    <div className="flex w-full text-sm !pt-0 p-1">
      <div className="flex w-full mb-auto">
        <FiBook className="mobile:hidden my-auto flex-none mr-2" size={14} />
        <div className="my-auto flex w-full items-center justify-between cursor-default">
          <span className="mobile:hidden">
            The AI decided this query didn&apos;t need a search
          </span>
          <p className="text-xs desktop:hidden">No search performed</p>
          <CustomTooltip
            content="Perform a search for this query"
            showTick
            line
            wrap
          >
            <button
              onClick={handleForceSearch}
              className="ml-auto mr-4 text-xs desktop:hidden underline-dotted decoration-dotted underline cursor-pointer"
            >
              Force search?
            </button>
          </CustomTooltip>
        </div>
      </div>
    </div>
  );
}
