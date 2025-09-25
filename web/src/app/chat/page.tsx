import { ChatPage } from "@/app/chat/components/ChatPage";

interface PageProps {
  searchParams: Promise<{ [key: string]: string }>;
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;

  return (
    <div className="flex flex-row w-full h-full justify-center items-center">
      {/* ModeSelector */}
      <div className="flex-1 h-full" />

      <div className="w-[60%] h-full">
        <ChatPage firstMessage={firstMessage} />
      </div>

      {/* DocumentExplorer */}
      <div className="flex-1 h-full" />
    </div>
  );
}
