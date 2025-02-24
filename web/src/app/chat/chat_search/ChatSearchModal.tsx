import React, { useRef, useEffect } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";
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
    createChat,
  } = useChatSearch({
    includeHighlights: true, // Enable search highlights
  });

  const router = useRouter();
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const handleChatSelect = (chatId: string) => {
    router.push(`/chat/${chatId}`);
    onClose();
  };

  const handleNewChat = async () => {
    try {
      const chatId = await createChat();
      router.push(`/chat/${chatId}`);
      onClose();
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
      >
        <div className="w-full flex flex-col bg-white dark:bg-gray-800 h-[80vh] max-h-[600px]">
          {/* Search header */}
          <div className="sticky top-0 z-20 px-6 py-3 w-full flex items-center justify-between bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            <div className="relative w-full">
              <div className="flex items-center">
                <Search className="h-4 w-4 mr-2 text-gray-400 dark:text-gray-500" />
                <Input
                  className="w-full border-none bg-transparent placeholder:text-gray-400 focus:border-transparent focus:outline-none focus:ring-0 dark:placeholder:text-gray-500 dark:text-gray-200"
                  placeholder="Search chats..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {isSearching && (
                  <div className="absolute right-2 top-1/2 -translate-y-1/2">
                    <LoadingSpinner size="small" />
                  </div>
                )}
              </div>
              {searchQuery && !isSearching && (
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1 ml-6">
                  Matching text will be highlighted
                </div>
              )}
            </div>
          </div>

          {/* Chat list */}
          <ScrollArea
            className="flex-grow bg-white dark:bg-gray-800"
            ref={scrollAreaRef}
            type="auto"
          >
            <div className="px-4 py-2">
              {/* New chat button */}
              <NewChatButton onClick={handleNewChat} />

              {/* Initial loading state */}
              {isLoading && chatGroups.length === 0 && (
                <div className="py-8">
                  <LoadingSpinner size="large" className="mx-auto" />
                </div>
              )}

              {/* Chat groups with sticky headers */}
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

                  {/* Load more indicator */}
                  <div ref={loadMoreRef} className="py-4">
                    {isLoading && hasMore && (
                      <LoadingSpinner className="mx-auto" />
                    )}
                    {!hasMore && chatGroups.length > 0 && (
                      <div className="text-center text-xs text-gray-500 dark:text-gray-400 py-2">
                        No more chats to load
                      </div>
                    )}
                  </div>
                </>
              ) : (
                !isLoading && (
                  <div className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
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
