import React from "react";

interface ImageProps {
  src: string;
  alt: string;
  width?: number;
  height?: number;
  fill?: boolean;
  [key: string]: unknown;
}

function Image({ src, alt, width, height, fill, ...props }: ImageProps) {
  const fillStyle: React.CSSProperties = fill
    ? { position: "absolute", inset: 0, width: "100%", height: "100%" }
    : {};
  return (
    <img
      {...(props as React.ImgHTMLAttributes<HTMLImageElement>)}
      src={src}
      alt={alt}
      width={fill ? undefined : width}
      height={fill ? undefined : height}
      style={{ ...(props.style as React.CSSProperties), ...fillStyle }}
    />
  );
}

export default Image;
