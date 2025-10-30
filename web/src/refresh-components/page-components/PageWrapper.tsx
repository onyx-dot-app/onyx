// Wraps all pages with the default, standard CSS styles.

export default function PageWrapper(
  props: React.HtmlHTMLAttributes<HTMLDivElement>
) {
  return (
    <div className="w-full h-full flex flex-col items-center justify-center overflow-y-scroll">
      <div className="min-w-[42rem]">
        <div {...props} />
      </div>
    </div>
  );
}
