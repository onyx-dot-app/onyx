import { fetchEEASettings } from "@/lib/eea/fetchEEASettings";
import WrappedChat from "./WrappedChat";
import { UserDisclaimerModal } from "@/components/search/UserDisclaimerModal";

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;

  const config = await fetchEEASettings();

  const {
    disclaimerTitle,
    disclaimerText
  } = config;

    return (
    <>
      <UserDisclaimerModal disclaimerText={disclaimerText} disclaimerTitle={disclaimerTitle}/>
      <WrappedChat firstMessage={firstMessage} />
    </>
  );
}
