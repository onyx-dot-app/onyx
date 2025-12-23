import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { unstable_noStore as noStore } from "next/cache";
import { redirect } from "next/navigation";
import type { Route } from "next";
import { requireAuth } from "@/lib/auth/requireAuth";
import { AssistantStats } from "./AssistantStats";
import { BackButton } from "@/components/BackButton";

export default async function GalleryPage(props: {
  params: Promise<{ id: string }>;
}) {
  const params = await props.params;
  noStore();

  // Only check authentication - data fetching is done client-side via SWR hooks
  const authResult = await requireAuth();

  if (authResult.redirect) {
    redirect(authResult.redirect as Route);
  }

  return (
    <>
      <div className="absolute top-4 left-4">
        <BackButton />
      </div>

      <div className="w-full py-8">
        <div className="px-32">
          <InstantSSRAutoRefresh />
          <div className="max-w-4xl mx-auto !border-none !bg-transparent !ring-none">
            <AssistantStats assistantId={parseInt(params.id)} />
          </div>
        </div>
      </div>
    </>
  );
}
