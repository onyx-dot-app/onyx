import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

export default function SearchSkeleton() {
  return (
    <div className="flex-1 min-h-0 w-full flex items-center justify-center">
      <SimpleLoader className="w-[7.5rem] h-[7.5rem]" />
    </div>
  );
}
