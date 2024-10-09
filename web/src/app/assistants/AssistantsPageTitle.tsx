export function AssistantsPageTitle({
  children,
}: {
  children: JSX.Element | string;
}) {
  return (
    <h1
      className="
      text-5xl 
      font-bold 
      mb-4 
      text-center
      text-text-900
    "
    >
      {children}
    </h1>
  );
}
