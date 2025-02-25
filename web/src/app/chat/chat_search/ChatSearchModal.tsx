import React, { useRef, useEffect } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Search, XIcon } from "lucide-react";
import { ChatSearchGroup } from "./ChatSearchGroup";
import { NewChatButton } from "./NewChatButton";
import { useChatSearch } from "./useChatSearch";
import { LoadingSpinner } from "./LoadingSpinner";
import { useRouter } from "next/navigation";

interface ChatSearchModalProps {
  open: boolean;
  onClose: () => void;
}

export function ChatSearchModal({ open, onClose }: ChatSearchModalProps) {
  const {
    searchQuery,
    setSearchQuery,
    chatGroups,
    isLoading,
    isSearching,
    hasMore,
    fetchMoreChats,
  } = useChatSearch();

  const router = useRouter();
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (!open) return;

    const options = {
      root: scrollAreaRef.current,
      rootMargin: "0px",
      threshold: 0.1,
    };

    const observer = new IntersectionObserver((entries) => {
      const [entry] = entries;
      if (entry.isIntersecting && hasMore && !isLoading) {
        fetchMoreChats();
      }
    }, options);

    if (loadMoreRef.current) {
      observer.observe(loadMoreRef.current);
    }

    observerRef.current = observer;

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [open, hasMore, isLoading, fetchMoreChats]);

  return (
    <Dialog open={open} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        hideCloseIcon
        className="!rounded-xl overflow-hidden p-0 w-full max-w-2xl"
        backgroundColor="bg-neutral-950/20 shadow-xl"
      >
        <div className="w-full flex flex-col bg-white dark:bg-neutral-800 h-[80vh] max-h-[600px]">
          <div className="sticky top-0 z-20 px-6 py-3 w-full flex items-center justify-between bg-white dark:bg-neutral-800 border-b border-neutral-200 dark:border-neutral-700">
            <div className="relative w-full">
              <div className="flex items-center">
                <Input
                  removeFocusRing
                  className="w-full !focus-visible:ring-offset-0 !focus-visible:ring-none !focus-visible:ring-0 hover:focus-none border-none bg-transparent placeholder:text-neutral-400 focus:border-transparent focus:outline-none focus:ring-0 dark:placeholder:text-neutral-500 dark:text-neutral-200"
                  placeholder="Search chats..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {searchQuery &&
                  (isSearching ? (
                    <div className="absolute right-2 top-1/2 -translate-y-1/2">
                      <LoadingSpinner size="small" />
                    </div>
                  ) : (
                    <XIcon
                      size={16}
                      className="absolute right-2 top-1/2 -translate-y-1/2"
                      onClick={() => setSearchQuery("")}
                    />
                  ))}
              </div>
              <div className="text-xs text-neutral-500 dark:text-neutral-400 mt-1 ml-3">
                {searchQuery && !isSearching
                  ? "Matching text will be highlighted"
                  : "Enter text to search through your chat history"}
              </div>
            </div>
          </div>

          {/* Chat list */}
          <ScrollArea
            className="flex-grow bg-white relative dark:bg-neutral-800"
            ref={scrollAreaRef}
            type="auto"
          >
            <div className="px-4  py-2">
              <NewChatButton onClick={handleNewChat} />

              {isLoading && chatGroups.length === 0 && (
                <div className="py-8">
                  <LoadingSpinner size="large" className="mx-auto" />
                </div>
              )}

              {chatGroups.length > 0 ? (
                <>
                  {chatGroups.map((group, groupIndex) => (
                    <ChatSearchGroup
                      key={groupIndex}
                      title={group.title}
                      chats={group.chats}
                      onSelectChat={handleChatSelect}
                    />
                  ))}

                  <div ref={loadMoreRef} className="py-4">
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
