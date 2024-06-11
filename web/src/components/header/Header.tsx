"use client";

import { User } from "@/lib/types";
import { logout } from "@/lib/user";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useContext, useEffect, useRef, useState } from "react";
import { CustomDropdown, DefaultDropdownElement } from "../Dropdown";
import { FiMessageSquare, FiSearch } from "react-icons/fi";
import { HeaderWrapper } from "./HeaderWrapper";
import { SettingsContext } from "../settings/SettingsProvider";
import { UserDropdown } from "../UserDropdown";

interface HeaderProps {
  user: User | null;
}

export function Header({ user }: HeaderProps) {
  const combinedSettings = useContext(SettingsContext);
  if (!combinedSettings) {
    return null;
  }
  const settings = combinedSettings.settings;

  return (
    <HeaderWrapper>
      <div className="flex h-full">
        <Link
          className="py-4"
          href={
            settings && settings.default_page === "chat" ? "/chat" : "/search"
          }
        >
          <div className="flex">
            <div className="h-[32px] w-[80px]">
              <Image
                src="/EEA_logo_compact_EN.svg"
                alt="Logo"
                width="1419"
                height="1520"
              />
            </div>
            <h1 className="flex text-2xl text-strong font-bold my-auto">
              &nbsp;GPT Lab
            </h1>
          </div>
        </Link>

        {(!settings ||
          (settings.search_page_enabled && settings.chat_page_enabled)) && (
          <>
            <Link
              href="/search"
              className={"ml-6 h-full flex flex-col hover:bg-hover"}
            >
              <div className="w-24 flex my-auto">
                <div className={"mx-auto flex text-strong px-2"}>
                  <FiSearch className="my-auto mr-1" />
                  <h1 className="flex text-sm font-bold my-auto">Search</h1>
                </div>
              </div>
            </Link>

            <Link href="/chat" className="h-full flex flex-col hover:bg-hover">
              <div className="w-24 flex my-auto">
                <div className="mx-auto flex text-strong px-2">
                  <FiMessageSquare className="my-auto mr-1" />
                  <h1 className="flex text-sm font-bold my-auto">Chat</h1>
                </div>
              </div>
            </Link>
          </>
        )}

        <div className="ml-auto h-full flex flex-col">
          <div className="my-auto">
            <UserDropdown user={user} hideChatAndSearch />
          </div>
        </div>
      </div>
    </HeaderWrapper>
  );
}

/* 

*/
