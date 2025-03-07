import { BasicClickable } from "@/components/BasicClickable";
import { CustomTooltip } from "@/components/tooltip/CustomTooltip";
import { FiBook } from "react-icons/fi";

export function SkippedSearch({
  handleForceSearch,
}: {
  handleForceSearch: () => void;
}) {
  return (
    <div className="flex w-full text-sm !pt-0 px-1">
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
            <>
              <BasicClickable
                onClick={handleForceSearch}
                className="ml-auto mr-4 -my-1 text-xs mobile:hidden bg-background/80 rounded-md px-2 py-1 cursor-pointer dark:hover:bg-neutral-700 dark:text-neutral-200"
              >
                Force search?
              </BasicClickable>
              <button
                onClick={handleForceSearch}
                className="ml-auto mr-4 text-xs desktop:hidden underline-dotted decoration-dotted underline cursor-pointer"
              >
                Force search?
              </button>
            </>
          </CustomTooltip>
        </div>
      </div>
    </div>
  );
}
