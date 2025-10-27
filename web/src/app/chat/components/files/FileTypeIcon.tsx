"use client";

import React from "react";
import SvgImage from "@/icons/image";
import SvgFileText from "@/icons/file-text";
import { getFileExtension, isImageExtension } from "./files_utils";

interface FileTypeIconProps {
  fileName: string;
  className?: string;
}

export default function FileTypeIcon({
  fileName,
  className,
}: FileTypeIconProps) {
  const ext = getFileExtension(fileName).toLowerCase();
  const isImage = isImageExtension(ext);
  if (isImage) {
    return <SvgImage className={className} />;
  }
  return <SvgFileText className={className} />;
}
