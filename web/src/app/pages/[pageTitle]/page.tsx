import { Header } from "@/components/header/Header";
import { Footer } from "@/components/Footer";
import { unstable_noStore as noStore } from "next/cache";
import {
  getCurrentUserSS,
} from "@/lib/userSS";
import { fetchSS } from "@/lib/utilsSS";
import { User } from "@/lib/types";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { notFound } from 'next/navigation'

export default async function Page({
  params,
}: {
  params: { pageTitle: string };
}) {

  noStore();
  const pageTitle = params.pageTitle;

  const tasks = [
    getCurrentUserSS(),
    fetchSS("/eea_config/get_eea_config"),
  ];
  let results: (
    | User
    | Response
    | null
  )[] = [null, null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }

  const user = results[0] as User | null;
  const EEAConfigResponse = results[1] as Response | null;

  let pageContent = "404";
  let eea_config = {"config": "" };
  if (EEAConfigResponse?.ok) {
    eea_config = await EEAConfigResponse.json();
    let conf;
    try{
      conf = JSON.parse(eea_config?.config)
    }
    catch(e){
      console.log("error parsing eea_conf")
    }
    pageContent = conf?.pages?.[pageTitle] || "404"
  }
  console.log(pageContent)
  if (pageContent === "404"){
    return notFound()
  }
  return (
    <>
      <Header user={user} />
      <div className="m-3">
        <HealthCheckBanner />
      </div>
      <div className="px-24 pt-10 flex flex-col items-center min-h-screen overflow-y-auto">
        <p dangerouslySetInnerHTML={{ __html: pageContent }} />
      </div> 
      <Footer eea_config={eea_config}/>
    </>
  );
}
