import { cn } from "@/lib/utils";

interface PreviewImageProps {
  src: string;
  alt: string;
  className?: string;
}

export default function PreviewImage({
  src,
  alt,
  className,
}: PreviewImageProps) {
  return (
    <img
      src={src}
      alt={alt}
      className={cn("object-contain object-center", className)}
    />
  );
}
