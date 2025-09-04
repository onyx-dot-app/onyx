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
      <div
        className={`${isRunning && "loading-text"} 
        !text-sm !line-clamp-1 !break-all !px-0.5`}
      >
        {toolName}
      </div>
    </div>
  );
}
