import { CustomTooltip } from "@/components/tooltip/CustomTooltip";
import { ReactNode } from "react";

// NOTE: This is the preivous version of the citations which works just fine
export function Citation({
  children,
  link,
  index,
}: {
  link?: string;
  children?: JSX.Element | string | null | ReactNode;
  index?: number;
}) {
  const innerText = children
    ? children?.toString().split("[")[1].split("]")[0]
    : index;

  if (link != "") {
    return (
      <CustomTooltip
        citation
        content={<div className="inline-block p-0 m-0 truncate">{link}</div>}
      >
        <a
          onMouseDown={() => (link ? window.open(link, "_blank") : undefined)}
          className="cursor-pointer inline ml-1 align-middle"
        >
          <span className="group relative -top-1 text-sm text-gray-500 dark:text-gray-400 selection:bg-indigo-300 selection:text-black dark:selection:bg-indigo-900 dark:selection:text-white">
            <span
              className="inline-flex bg-background-200 group-hover:bg-background-300 items-center justify-center h-3.5 min-w-3.5 px-1 text-center text-xs rounded-full border-1 border-gray-400 ring-1 ring-gray-400 divide-gray-300 dark:divide-gray-700 dark:ring-gray-700 dark:border-gray-700 transition duration-150"
              data-number="3"
            >
              {innerText}
            </span>
          </span>
        </a>
      </CustomTooltip>
    );
  } else {
    return (
      <CustomTooltip content={<div>This doc doesn&apos;t have a link!</div>}>
        <div className="inline-block cursor-help leading-none inline ml-1 align-middle">
          <span className="group relative -top-1 text-gray-500 dark:text-gray-400 selection:bg-indigo-300 selection:text-black dark:selection:bg-indigo-900 dark:selection:text-white">
            <span
              className="inline-flex bg-background-200 group-hover:bg-background-300 items-center justify-center h-3.5 min-w-3.5 flex-none px-1 text-center text-xs rounded-full border-1 border-gray-400 ring-1 ring-gray-400 divide-gray-300 dark:divide-gray-700 dark:ring-gray-700 dark:border-gray-700 transition duration-150"
              data-number="3"
            >
              {innerText}
            </span>
          </span>
        </div>
      </CustomTooltip>
    );
  }
}
