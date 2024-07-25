"use client";
import { SearchSection } from "@/components/search/SearchSection";
import FunctionalWrapper from "../chat/shared_chat_search/FunctionalWrapper";
import { CCPairBasicInfo, DocumentSet, Tag, User } from "@/lib/types";
import { Persona } from "../admin/assistants/interfaces";
import { ChatSession } from "../chat/interfaces";

export default function WrappedSearch({
  querySessions,
  ccPairs,
  documentSets,
  personas,
  searchTypeDefault,
  tags,
  user,
  agenticSearchEnabled,
  initiallyToggled,
  disabledAgentic,
}: {
  disabledAgentic: boolean;
  querySessions: ChatSession[];
  ccPairs: CCPairBasicInfo[];
  documentSets: DocumentSet[];
  personas: Persona[];
  searchTypeDefault: string;
  tags: Tag[];
  user: User | null;
  agenticSearchEnabled: boolean;
  initiallyToggled: boolean;
}) {
  return (
    <FunctionalWrapper
      initiallyToggled={initiallyToggled}
      content={(toggledSidebar, toggle) => (
        <SearchSection
          disabledAgentic={disabledAgentic}
          agenticSearchEnabled={agenticSearchEnabled}
          toggle={toggle}
          toggledSidebar={toggledSidebar}
          querySessions={querySessions}
          user={user}
          ccPairs={ccPairs}
          documentSets={documentSets}
          personas={personas}
          tags={tags}
          defaultSearchType={searchTypeDefault}
        />
      )}
    />
  );
}
