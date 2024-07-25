"use client";

import { User } from "@/lib/types";
import Link from "next/link";
import React, { useContext } from "react";
import { FiMessageSquare, FiSearch } from "react-icons/fi";
import { HeaderWrapper } from "./HeaderWrapper";
import { SettingsContext } from "../settings/SettingsProvider";
import { UserDropdown } from "../UserDropdown";
import { Logo } from "../Logo";
import { NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED } from "@/lib/constants";

export function HeaderTitle({ children }: { children: JSX.Element | string }) {
  return <h1 className="flex text-2xl text-strong font-bold">{children}</h1>;
}

interface HeaderProps {
  user: User | null;
  page?: "search" | "chat" | "assistants";
}

export function Header({ user, page }: HeaderProps) {
  const combinedSettings = useContext(SettingsContext);
  if (!combinedSettings) {
    return null;
  }
  const settings = combinedSettings.settings;
  const enterpriseSettings = combinedSettings.enterpriseSettings;

  return (
    <HeaderWrapper>
      <div className="flex h-full">
        <Link
          className="py-3 flex flex-col"
          href={
            settings && settings.default_page === "chat" ? "/chat" : "/search"
          }
        >
          <div className="flex my-auto">
            <div className="mr-1 my-auto">
              <Logo />
            </div>
            <div className="my-auto">
              {enterpriseSettings && enterpriseSettings.application_name ? (
                <div>
                  <HeaderTitle>
                    {enterpriseSettings.application_name}
                  </HeaderTitle>
                  {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && (
                    <p className="text-xs text-subtle -mt-1.5">
                      Powered by Danswer
                    </p>
                  )}
                </div>
              ) : (
                <HeaderTitle>Danswer</HeaderTitle>
              )}
            </div>
          </div>
        </Link>

        <div className="ml-auto h-full flex flex-col">
          <div className="my-auto">
            <UserDropdown user={user} page={page} />
          </div>
        </div>
      </div>
    </HeaderWrapper>
  );
}

/* 

*/
