export function HeaderWrapper({
  children,
}: {
  children: JSX.Element | string;
}) {
  return (
    <header className="border-b border-border bg-background-emphasis">
      <div className="mx-8 h-16">{children}</div>
    </header>
  );
}
