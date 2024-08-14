import { Quote } from "@/lib/search/interfaces";
import { ResponseSection, StatusOptions } from "./ResponseSection";
import { CheckmarkIcon, CopyIcon } from "@/components/icons/icons";
import { useState } from "react";
import { SourceIcon } from "@/components/SourceIcon";
import { Button } from "@/components/ui/button";

const QuoteDisplay = ({ quoteInfo }: { quoteInfo: Quote }) => {
  const [detailIsOpen, setDetailIsOpen] = useState(false);
  const [copyClicked, setCopyClicked] = useState(false);

  return (
    <div
      className="relative"
      onMouseEnter={() => {
        setDetailIsOpen(true);
      }}
      onMouseLeave={() => setDetailIsOpen(false)}
    >
      {detailIsOpen && (
        <div className="absolute top-0 mt-9 pt-2 z-50">
          <div className="flex flex-shrink-0 rounded-regular w-96 bg-background border border-border shadow p-3 text-sm leading-relaxed">
            <div>
              <b>Quote:</b> <i>{quoteInfo.quote}</i>
            </div>
            <div
              className="my-auto pl-3 ml-auto"
              onClick={() => {
                navigator.clipboard.writeText(quoteInfo.quote);
                setCopyClicked(true);
                setTimeout(() => {
                  setCopyClicked(false);
                }, 1000);
              }}
            >
              <div className="p-1 rounded hover:bg-hover cursor-pointer">
                {copyClicked ? (
                  <CheckmarkIcon
                    className="my-auto flex flex-shrink-0"
                    size={16}
                  />
                ) : (
                  <CopyIcon className="my-auto flex flex-shrink-0" size={16} />
                )}
              </div>
            </div>
          </div>
        </div>
      )}
      <div className="text-sm flex w-fit">
        {/* <a
          className="flex max-w-sidebar shrink box-border p-2 border border-border rounded-regular hover:bg-hover-light"
          href={quoteInfo.link || undefined}
          target="_blank"
          rel="noopener noreferrer"
        >
          <SourceIcon sourceType={quoteInfo.source_type} iconSize={18} />
          <p className="truncate break-all ml-2 mr-2">
            {quoteInfo.semantic_identifier || quoteInfo.document_id}
          </p>
        </a> */}
        <a
          href={quoteInfo.link || undefined}
          target="_blank"
          rel="noopener noreferrer"
        >
          <Button variant="outline">
            <SourceIcon sourceType={quoteInfo.source_type} iconSize={18} />
            <p className="truncate break-all ml-2 mr-2">
              {quoteInfo.semantic_identifier || quoteInfo.document_id}
            </p>
          </Button>
        </a>

        {/* <div
          className="cursor-pointer h-full pt-2 pb-2 px-1 border-t border-b border-r border-gray-800 rounded-r-lg hover:bg-gray-800"
          onClick={() => setDetailIsOpen(!detailIsOpen)}
        >
          <div className="pt-0.5 mx-auto h-[20px]">
            <ZoomInIcon className="text-gray-500" size={14} />
          </div>
        </div> */}
      </div>
    </div>
  );
};

interface QuotesSectionProps {
  quotes: Quote[] | null;
  isAnswerable: boolean | null;
  isFetching: boolean;
}

const QuotesHeader = ({ quotes, isFetching }: QuotesSectionProps) => {
  if ((!quotes || quotes.length === 0) && isFetching) {
    return <>Extracting quotes...</>;
  }

  if (!quotes || quotes.length === 0) {
    return <>No quotes found</>;
  }

  return <>Quotes</>;
};

const QuotesBody = ({ quotes, isFetching }: QuotesSectionProps) => {
  if (!quotes && isFetching) {
    // height of quotes section to avoid extra "jumps" from the quotes loading
    return <div className="h-[42px]"></div>;
  }

  if (!isFetching && (!quotes || !quotes.length)) {
    return (
      <div className="flex">
        <div className="text-error text-sm my-auto">
          Did not find any exact quotes to support the above answer.
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {quotes!.map((quoteInfo) => (
        <QuoteDisplay quoteInfo={quoteInfo} key={quoteInfo.document_id} />
      ))}
    </div>
  );
};

export const QuotesSection = (props: QuotesSectionProps) => {
  let status: StatusOptions = "in-progress";
  if (!props.isFetching) {
    if (props.quotes && props.quotes.length > 0) {
      if (props.isAnswerable === false) {
        status = "warning";
      } else {
        status = "success";
      }
    } else {
      status = "failed";
    }
  }

  return (
    <ResponseSection
      status={status}
      header={
        <div className="ml-2 text-emphasis">{<QuotesHeader {...props} />}</div>
      }
      body={<QuotesBody {...props} />}
      desiredOpenStatus={true}
      isNotControllable={true}
    />
  );
};
