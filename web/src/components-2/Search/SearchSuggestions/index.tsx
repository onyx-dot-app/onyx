import { errorHandlingFetcher } from "@/lib/fetcher";
import React from "react";
import useSWR from "swr";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
} from "@/components/ui/carousel";
import Autoplay from "embla-carousel-autoplay";

const DELAY_MS = 5000;

interface SearchSuggestionsProps {
  onSuggestionClick?: (suggestion: string) => void;
}

export default function SearchSuggestions({
  onSuggestionClick,
}: SearchSuggestionsProps) {
  const { data: suggestions, isLoading } = useSWR<string[]>(
    "/api/search/suggestions",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      revalidateOnReconnect: false,
    }
  );

  if (isLoading || !suggestions || suggestions.length === 0) {
    return (
      <div className="w-full px-4 h-[160px] flex flex-col gap-2">
        {[...Array(4)].map((_, index) => (
          <div key={index} className="p-2 rounded-md">
            <div className="h-4 bg-neutral-200 dark:bg-neutral-700 rounded animate-pulse w-3/4"></div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="w-full px-4">
      <Carousel
        orientation="vertical"
        opts={{
          align: "start",
          loop: true,
          watchDrag: false,
        }}
        plugins={[Autoplay({ delay: DELAY_MS, stopOnInteraction: false })]}
      >
        <CarouselContent className="h-44">
          {suggestions.map((suggestion, index) => (
            <CarouselItem key={index} className="-mt-4 basis-1/4">
              <div
                className="p-2 rounded-md hover:bg-gray-100 cursor-pointer transition-colors"
                onClick={() => onSuggestionClick?.(suggestion)}
              >
                <span className="text-sm text-neutral-500">{suggestion}</span>
              </div>
            </CarouselItem>
          ))}
        </CarouselContent>
      </Carousel>
    </div>
  );
}
