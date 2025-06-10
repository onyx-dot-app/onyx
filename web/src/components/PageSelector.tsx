import React from "react";

const PAGINATION_OPTIONS_ON_EACH_SIDE = 2;

const getPaginationOptions = (
  currentPage: number,
  pageCount: number
): number[] => {
  const paginationOptions = [currentPage];
  // if (currentPage !== 1) {
  //   paginationOptions.push(currentPage)
  // }

  let offset = 1;

  // Add one because currentPage is included
  const maxPaginationOptions = PAGINATION_OPTIONS_ON_EACH_SIDE * 2 + 1;
  while (paginationOptions.length < maxPaginationOptions) {
    let added = false;
    if (currentPage + offset <= pageCount) {
      paginationOptions.push(currentPage + offset);
      added = true;
    }
    if (currentPage - offset >= 1) {
      paginationOptions.unshift(currentPage - offset);
      added = true;
    }
    if (!added) {
      break;
    }
    offset++;
  }

  return paginationOptions;
};

const scrollUp = () => {
  setTimeout(() => window.scrollTo({ top: 0 }), 50);
};

type PageLinkProps = {
  linkText: string | number;
  pageChangeHandler?: () => void;
  active?: boolean;
  unclickable?: boolean;
};

const PageLink = ({
  linkText,
  pageChangeHandler,
  active,
  unclickable,
}: PageLinkProps) => (
  <div
    className={`
    select-none
    inline-block
    text-sm
    border
    px-3
    py-1
    leading-5
    -ml-px
    border-border
    ${unclickable ? "text-text-200" : ""}
    ${!unclickable ? "hover:bg-accent-background-hovered" : ""}
    ${!unclickable ? "cursor-pointer" : ""}
    first:ml-0
    first:rounded-l-md
    last:rounded-r-md
    ${active ? "bg-background-200" : ""}
  `}
    onClick={() => {
      if (pageChangeHandler) {
        pageChangeHandler();
      }
    }}
  >
    {linkText}
  </div>
);

export interface PageSelectorProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (newPage: number) => void;
  shouldScroll?: boolean;
}

export const PageSelector = ({
  currentPage,
  totalPages,
  onPageChange,
  shouldScroll = false,
}: PageSelectorProps) => {
  const paginationOptions = getPaginationOptions(currentPage, totalPages);
  const modifiedScrollUp = () => {
    if (shouldScroll) {
      scrollUp();
    }
  };

  return (
    <div style={{ display: "inline-block" }}>
      <PageLink
        linkText="‹"
        unclickable={currentPage === 1}
        pageChangeHandler={() => {
          onPageChange(Math.max(currentPage - 1, 1));
          modifiedScrollUp();
        }}
      />
      {!paginationOptions.includes(1) && (
        <>
          <PageLink
            linkText="1"
            active={currentPage === 1}
            pageChangeHandler={() => {
              onPageChange(1);
              modifiedScrollUp();
            }}
          />
          <PageLink linkText="..." unclickable={true} />
        </>
      )}
      {(!paginationOptions.includes(1)
        ? paginationOptions.slice(2)
        : paginationOptions
      ).map((page) => {
        return (
          <PageLink
            key={page}
            active={page === currentPage}
            linkText={page}
            pageChangeHandler={() => {
              onPageChange(page);
              modifiedScrollUp();
            }}
          />
        );
      })}
      <PageLink
        linkText="›"
        unclickable={currentPage === totalPages}
        pageChangeHandler={() => {
          onPageChange(Math.min(currentPage + 1, totalPages));
          modifiedScrollUp();
        }}
      />
    </div>
  );
};
