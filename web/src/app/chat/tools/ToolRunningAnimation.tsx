import { LoadingAnimation } from "@/components/Loading";

export function ToolRunDisplay({
  toolName,
  toolLogo,
  isRunning,
}: {
  toolName: string;
  toolLogo?: JSX.Element;
  isRunning: boolean;
}) {
  return (
    <div className="text-sm text-subtle my-auto flex">
      {toolLogo}
      {isRunning ? <LoadingAnimation text={toolName} /> : toolName}
    </div>
  );
}
