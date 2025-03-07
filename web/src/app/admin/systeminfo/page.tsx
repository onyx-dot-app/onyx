import { NotebookIcon } from "@/components/icons/icons";
import { getWebVersion, getBackendVersion } from "@/lib/version";

const Page = async () => {
  let web_version: string | null = null;
  let backend_version: string | null = null;
  try {
    [web_version, backend_version] = await Promise.all([
      getWebVersion(),
      getBackendVersion(),
    ]);
  } catch (e) {
    console.log(`Version info fetch failed for system info page - ${e}`);
  }

  return (
    <div>
      <div className="border-solid border-background-600 border-b pb-2 mb-4 flex">
        <NotebookIcon size={32} />
        <h1 className="text-3xl font-bold pl-2">Version</h1>
      </div>

      <div>
        <div className="flex mb-2">
          <p className="my-auto mr-1">Backend Version: </p>
          <p className="text-base my-auto text-slate-400 italic">
            {backend_version}
          </p>
        </div>
        <div className="flex mb-2">
          <p className="my-auto mr-1">Web Version: </p>
          <p className="text-base my-auto text-slate-400 italic">
            {web_version}
          </p>
        </div>
      </div>
    </div>
  );
};

export default Page;
