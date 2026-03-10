import Separator from "@/refresh-components/Separator";

function SearchSkeletonCard() {
  return (
    <div className="flex flex-col gap-2 p-4 rounded-12 bg-background-neutral-01 animate-pulse">
      <div className="flex flex-row items-center gap-2">
        <div className="w-4 h-4 rounded bg-background-neutral-03" />
        <div className="h-3 w-32 rounded bg-background-neutral-03" />
      </div>
      <div className="h-4 w-3/4 rounded bg-background-neutral-03" />
      <div className="flex flex-col gap-1.5">
        <div className="h-3 w-full rounded bg-background-neutral-03" />
        <div className="h-3 w-5/6 rounded bg-background-neutral-03" />
      </div>
    </div>
  );
}

export default function SearchSkeleton() {
  return (
    <div className="flex-1 min-h-0 w-full flex flex-col gap-3">
      <div className="flex-shrink-0 flex flex-row gap-x-4">
        <div className="flex flex-col justify-end gap-3 flex-[3]">
          <div className="flex flex-row gap-2">
            <div className="h-8 w-24 rounded bg-background-neutral-02 animate-pulse" />
            <div className="h-8 w-20 rounded bg-background-neutral-02 animate-pulse" />
          </div>
          <Separator noPadding />
        </div>
        <div className="flex-1 flex flex-col justify-end gap-3">
          <div className="h-4 w-16 rounded bg-background-neutral-02 animate-pulse" />
          <Separator noPadding />
        </div>
      </div>
      <div className="flex-1 min-h-0 flex flex-row gap-x-4">
        <div className="min-h-0 flex-[3] flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <SearchSkeletonCard key={i} />
          ))}
        </div>
        <div className="flex-1 flex flex-col gap-2 px-1">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-8 w-full rounded bg-background-neutral-02 animate-pulse"
            />
          ))}
        </div>
      </div>
    </div>
  );
}
