// Wraps all pages with the default, standard CSS styles.

export default function PageWrapper(
  props: React.HtmlHTMLAttributes<HTMLDivElement>
) {
  return (
    <div className="w-full h-full flex flex-col items-center overflow-y-auto">
      <div className="h-full w-[50rem]">
        <div {...props} />
      </div>
    </div>
  );
}
