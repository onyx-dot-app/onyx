import React from "react";

interface ImageProps {
  src: string;
  alt: string;
  width?: number;
  height?: number;
  [key: string]: unknown;
}

function Image({ src, alt, width, height, ...props }: ImageProps) {
  return <img src={src} alt={alt} width={width} height={height} {...props} />;
}

export default Image;
