import AppPage from "@/views/AppPage";
import { defaultAgentRedirectTarget } from "@/lib/app/utils";
import { redirect } from "next/navigation";

export interface PageProps {
  searchParams: Promise<{ [key: string]: string }>;
}

export default async function Page(props: PageProps) {
  const searchParams = await props.searchParams;

  const redirectTarget = defaultAgentRedirectTarget(searchParams);
  if (redirectTarget) redirect(redirectTarget);

  const firstMessage = searchParams.firstMessage;

  // Other pages in `web/src/app/chat` are wrapped with `<AppPageLayout>`.
  // `chat/page.tsx` is not because it also needs to handle rendering of the document-sidebar (`web/src/sections/document-sidebar/DocumentsSidebar.tsx`).
  return <AppPage firstMessage={firstMessage} />;
}
