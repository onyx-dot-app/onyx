import { ChatPage } from "./components/ChatPage";

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;

  return <ChatPage firstMessage={firstMessage} />;
}
