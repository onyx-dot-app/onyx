import React, { useRef } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChatSearchGroup } from "./ChatSearchGroup";
import { NewChatButton } from "./NewChatButton";
import { useChatSearch } from "./hooks/useChatSearch";
import { LoadingSpinner } from "./LoadingSpinner";
import { useRouter } from "next/navigation";
import { SearchInput } from "./components/SearchInput";
import { ChatSearchSkeletonList } from "./components/ChatSearchSkeleton";
import { useIntersectionObserver } from "./hooks/useIntersectionObserver";

interface ChatSearchModalProps {
  open: boolean;
  onCloseModal: () => void;
}

export function ChatSearchModal({ open, onCloseModal }: ChatSearchModalProps) {
  const {
    searchQuery,
    setSearchQuery,
    chatGroups,
    isLoading,
    isSearching,
    hasMore,
    fetchMoreChats,
  } = useChatSearch();

  const onClose = () => {
    setSearchQuery("");
    onCloseModal();
  };

  const router = useRouter();
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const { targetRef } = useIntersectionObserver({
    root: scrollAreaRef.current,
    onIntersect: fetchMoreChats,
    enabled: open && hasMore && !isLoading,
  });

  const handleChatSelect = (chatId: string) => {
    router.push(`/chat?chatId=${chatId}`);
    onClose();
  };

  const handleNewChat = async () => {
    try {
      onClose();
      router.push(`/chat`);
    } catch (error) {
      console.error("Error creating new chat:", error);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        hideCloseIcon
        className="!rounded-xl overflow-hidden p-0 w-full max-w-2xl"
        backgroundColor="bg-neutral-950/20 shadow-xl"
      >
        <div className="w-full flex flex-col bg-white dark:bg-neutral-800 h-[80vh] max-h-[600px]">
          <div className="sticky top-0 z-20 px-6 py-3 w-full flex items-center justify-between bg-white dark:bg-neutral-800 border-b border-neutral-200 dark:border-neutral-700">
            <SearchInput
              searchQuery={searchQuery}
              setSearchQuery={setSearchQuery}
              isSearching={isSearching}
            />
          </div>

          <ScrollArea
            className="flex-grow bg-white relative dark:bg-neutral-800"
            ref={scrollAreaRef}
            type="auto"
          >
            <div className="px-4 py-2">
              <NewChatButton onClick={handleNewChat} />

              {isSearching ? (
                <ChatSearchSkeletonList />
              ) : isLoading && chatGroups.length === 0 ? (
                <div className="py-8">
                  <LoadingSpinner size="large" className="mx-auto" />
                </div>
              ) : chatGroups.length > 0 ? (
                <>
                  {chatGroups.map((group, groupIndex) => (
                    <ChatSearchGroup
                      key={groupIndex}
                      title={group.title}
                      chats={group.chats}
                      onSelectChat={handleChatSelect}
                    />
                  ))}

                  <div ref={targetRef} className="py-4">
                    {isLoading && hasMore && (
                      <LoadingSpinner className="mx-auto" />
                    )}
                    {!hasMore && chatGroups.length > 0 && (
                      <div className="text-center text-xs text-neutral-500 dark:text-neutral-400 py-2">
                        No more chats to load
                      </div>
                    )}
                  </div>
                </>
              ) : (
                !isLoading && (
                  <div className="px-4 py-3 text-sm text-neutral-500 dark:text-neutral-400">
                    No chats found
                  </div>
                )
              )}
            </div>
          </ScrollArea>
        </div>
      </DialogContent>
    </Dialog>
  );
}
