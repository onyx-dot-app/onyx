import { useRouter } from "next/router";
import { ChatSession } from "@/app/chat/interfaces";

export const ChatGroup = ({
  groupName,
  toggled,
  chatSessions,
}: {
  groupName: string;
  toggled: boolean;
  chatSessions: ChatSession[];
}) => {
  const router = useRouter();

  return toggled ? (
    <div>
      <p>{groupName}</p>
    </div>
  ) : null;
};
