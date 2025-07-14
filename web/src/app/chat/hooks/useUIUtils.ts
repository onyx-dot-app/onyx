import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

export function useScreenSize() {
  const [screenSize, setScreenSize] = useState({
    width: typeof window !== "undefined" ? window.innerWidth : 0,
    height: typeof window !== "undefined" ? window.innerHeight : 0,
  });

  useEffect(() => {
    const handleResize = () => {
      setScreenSize({
        width: window.innerWidth,
        height: window.innerHeight,
      });
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return screenSize;
}

/**
 * @param onError - Function to call when an redirect fails
 * @param setIsLoading - Function to notify the parent that the redirect is in progress
 */
export function useSlackChatRedirect(
  onError: (error: any) => void,
  setIsLoading: (isLoading: boolean) => void
) {
  const router = useRouter();

  useEffect(() => {
    const handleSlackChatRedirect = async () => {
      const urlParams = new URLSearchParams(window.location.search);
      const slackChatId = urlParams.get("slackChatId");

      if (!slackChatId) return;

      // Notify the parent that the redirect is in progress
      setIsLoading(true);

      try {
        const response = await fetch("/api/chat/seed-chat-session-from-slack", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            chat_session_id: slackChatId,
          }),
        });

        if (!response.ok) {
          throw new Error("Failed to seed chat from Slack");
        }

        const data = await response.json();

        router.push(data.redirect_url);
      } catch (error) {
        console.error("Error seeding chat from Slack:", error);

        onError(error);
      }
    };

    handleSlackChatRedirect();
  }, [router, onError, setIsLoading]);
}
