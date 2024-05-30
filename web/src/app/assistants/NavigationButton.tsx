export function NavigationButton({
  children,
}: {
  children: JSX.Element | string;
}) {
  return (
    <div
      className="
        text-default
        py-2
        px-4
        rounded-full
        border-2
        border-border
        hover:bg-hover
        focus:outline-none
        focus:ring-2
        focus:ring-border
        focus:ring-opacity-50
      "
    >
      {children}
    </div>
  );
}
