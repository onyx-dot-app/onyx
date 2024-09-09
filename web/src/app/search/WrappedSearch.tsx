"use client";
import { SearchSection } from "@/components/search/SearchSection";
import FunctionalWrapper from "../chat/shared_chat_search/FunctionalWrapper";

export default function WrappedSearch({
  searchTypeDefault,
  initiallyToggled,
}: {
  searchTypeDefault: string;
  initiallyToggled: boolean;
}) {
  return (
    <FunctionalWrapper
      initiallyToggled={initiallyToggled}
      content={(toggledSidebar, toggle) => (
        <SearchSection
          toggle={toggle}
          toggledSidebar={toggledSidebar}
          defaultSearchType={searchTypeDefault}
        />
      )}
    />
  );
}
