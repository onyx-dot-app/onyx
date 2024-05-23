import { LoadingAnimation } from "@/components/Loading";

export function ToolRunningAnimation({
  toolName,
  toolLogo,
}: {
  toolName: string;
  toolLogo: JSX.Element;
}) {
  return (
    <div className="text-sm my-auto flex">
      {toolLogo}
      <LoadingAnimation text={toolName} />
    </div>
  );
}
