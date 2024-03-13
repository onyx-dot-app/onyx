"use client";

import Image from "next/image";
import Link from "next/link";
import React from "react";
import { FiMessageSquare, FiSearch } from "react-icons/fi";

interface FooterProps {
}

export const Footer: React.FC<FooterProps> = () => {


  return (
    <footer className="border-b border-border bg-background-emphasis">
      <div className="mx-8 flex h-16">
        <Link className="py-4" href="https://Danswer.ai" target="_blank">
          <div className="flex">
            <div className="h-[32px] w-[30px]">
              <Image src="/logo.png" alt="Logo" width="1419" height="1520" />
            </div>
            <h3 className="flex text-xl text-strong my-auto">
              &nbsp;Powered by Danswer.ai
            </h3>
          </div>
        </Link>
      </div>
    </footer>
  );
};

/* 

*/
