export function AssistantsPageTitle({
  children,
}: {
  children: JSX.Element | string;
}) {
  return (
    <h1
      className="
      text-4xl 
      font-bold 
      mb-4 
      text-center
    "
    >
      {children}
    </h1>
  );
}
