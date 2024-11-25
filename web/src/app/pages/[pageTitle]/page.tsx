import { use } from "react";

import { unstable_noStore as noStore } from "next/cache";
import {
  getCurrentUserSS,
} from "@/lib/userSS";
import { fetchSS } from "@/lib/utilsSS";
import { User } from "@/lib/types";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { notFound } from 'next/navigation'
import { fetchEEASettings } from "@/lib/eea/fetchEEASettings";
import FixedLogo from "@/app/chat/shared_chat_search/FixedLogo";
//import { useRouter } from "next/navigation";
import { BackIcon } from "@/components/icons/icons";
import Link from "next/link";

// export default async function Page({
//   params,
// }: {
//   params: { pageTitle: string };
// }) {
export default async function Page(props: { params: Promise<{ pageTitle: string }> }) {
  const params = await props.params;

  noStore();
  const pageTitle = params.pageTitle;

  const tasks = [
    getCurrentUserSS(),
  ];
  let results: (
    | User
    | null
  )[] = [null, null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }
  const config = await fetchEEASettings();
  
  const {
    eea_config,
  } = config;
  
  const user = results[0] as User | null;

  let pageContent = "404";
  pageContent = eea_config?.pages?.[pageTitle] || "404"
  if (pageContent === "404"){
    return notFound()
  }
  return (
    <>
      <div className="m-3">
        <HealthCheckBanner />
      </div>
      <Link href={"/chat"}>
            <button className="text-sm block w-52 py-2.5 flex px-2 text-left bg-background-200 hover:bg-background-200/80 cursor-pointer rounded">
              <BackIcon size={20} className="text-neutral" />
              <p className="ml-1">Back to GPT Lab</p>
            </button>
          </Link>

      <div className="px-24 pt-10 flex flex-col items-center min-h-screen overflow-y-auto">
        <p dangerouslySetInnerHTML={{ __html: pageContent }} />
      </div> 

    </>
  );
}
