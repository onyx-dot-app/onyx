import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
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
            {i18n.t(k.THE_AI_DECIDED_THIS_QUERY_DIDN)}
          </span>
          <p className="text-xs desktop:hidden">
            {i18n.t(k.NO_SEARCH_PERFORMED)}
          </p>
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
                {i18n.t(k.FORCE_SEARCH)}
              </BasicClickable>
              <button
                onClick={handleForceSearch}
                className="ml-auto mr-4 text-xs desktop:hidden underline-dotted decoration-dotted underline cursor-pointer"
              >
                {i18n.t(k.FORCE_SEARCH)}
              </button>
            </>
          </CustomTooltip>
        </div>
      </div>
    </div>
  );
}
