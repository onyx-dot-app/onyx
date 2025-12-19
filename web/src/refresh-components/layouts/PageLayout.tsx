// Wraps all pages with the default, standard CSS styles.

export default function PageWrapper(
  props: React.HtmlHTMLAttributes<HTMLDivElement>
) {
  return (
    <div
      id="page-wrapper-scroll-container"
      className="w-full h-full flex flex-col items-center overflow-y-auto"
    >
      {/* WARNING: The id="page-wrapper-scroll-container" above is used by PageHeader.tsx
          to detect scroll position and show/hide the scroll shadow.
          DO NOT REMOVE this ID without updating PageHeader.tsx accordingly. */}
      <div className="h-full w-[min(50rem,100%)]">
        <div {...props} />
      </div>
    </div>
  );
}
