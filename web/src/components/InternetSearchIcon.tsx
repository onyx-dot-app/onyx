export function InternetSearchIcon({ url }: { url: string }) {
  return (
    <img
      className="rounded-full w-[18px] h-[18px]"
      src={`https://www.google.com/s2/favicons?sz=128&domain=${url}`}
      alt="favicon"
    />
  );
}
