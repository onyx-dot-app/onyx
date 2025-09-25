import { ChatPage } from "@/app/chat/components/ChatPage";

interface PageProps {
  searchParams: Promise<{ [key: string]: string }>;
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;

  return <ChatPage firstMessage={firstMessage} />;
}
