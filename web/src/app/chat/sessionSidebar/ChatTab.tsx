import { ChatSession } from "../interfaces";
import { groupSessionsByDateRange } from "../lib";
import { ChatSessionDisplay } from "./SessionDisplay";

export function ChatTab({
  existingChats,
  currentChatId,
}: {
  existingChats: ChatSession[];
  currentChatId?: number;
}) {
  const groupedChatSessions = groupSessionsByDateRange(existingChats);

  return (
    <div className="mt-1 pb-1 mb-1 ml-3 overflow-y-auto h-full">
      {Object.entries(groupedChatSessions).map(([dateRange, chatSessions]) => {
        if (chatSessions.length > 0) {
          return (
            <div key={dateRange}>
              <div className="text-xs text-subtle flex pb-0.5 mb-1.5 mt-5 font-bold">
                {dateRange}
              </div>
              {chatSessions.map((chat) => {
                const isSelected = currentChatId === chat.id;
                return (
                  <div key={`${chat.id}-${chat.name}`} className="mr-3">
                    <ChatSessionDisplay
                      chatSession={chat}
                      isSelected={isSelected}
                    />
                  </div>
                );
              })}
            </div>
          );
        }
      })}
    </div>
  );
}
