"use client";

import React, { useState, useEffect } from "react";
import "./loading.css";
import { ThreeDots } from "react-loader-spinner";
import { cn } from "@/lib/utils";

interface LoadingAnimationProps {
  text?: string;
  size?: "text-sm" | "text-md";
}

export const LoadingAnimation: React.FC<LoadingAnimationProps> = ({
  text,
  size,
}) => {
  const [dots, setDots] = useState("...");

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((prevDots) => {
        switch (prevDots) {
          case ".":
            return "..";
          case "..":
            return "...";
          case "...":
            return ".";
          default:
            return "...";
        }
      });
    }, 500);

    return () => clearInterval(interval);
  }, []);

  return (
    <span className="loading-animation inline-flex">
      <span className={cn("mx-auto inline-flex", size)}>
        {text === undefined ? "Thinking" : text}
        <span className="dots">{dots}</span>
      </span>
    </span>
  );
};

export const ThreeDotsLoader = () => {
  return (
    <div className="flex my-auto">
      <div className="mx-auto">
        <ThreeDots
          height="30"
          width="50"
          color="#3b82f6"
          ariaLabel="grid-loading"
          radius="12.5"
          wrapperStyle={{}}
          wrapperClass=""
          visible={true}
        />
      </div>
    </div>
  );
};
