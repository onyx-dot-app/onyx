"use client";

import AgentEditorPage from "@/refresh-pages/AgentEditorPage";

export interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function Page(props: PageProps) {
  const { id } = await props.params;
  // const [values, error] = await fetchAgentEditorInfoSS(id);
  // if (!values) {
  //   return (
  //     <div className="px-32">
  //       <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
  //     </div>
  //   );
  // }

  return <AgentEditorPage />;
}
