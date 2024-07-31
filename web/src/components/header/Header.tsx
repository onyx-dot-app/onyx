"use client";

import { User } from "@/lib/types";
import Link from "next/link";
import React, { useContext } from "react";
import { HeaderWrapper } from "./HeaderWrapper";
import { SettingsContext } from "../settings/SettingsProvider";
import { UserDropdown } from "../UserDropdown";
import { Logo } from "../EEA_Logo";
import { NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED } from "@/lib/constants";
import { pageType } from "@/app/chat/sessionSidebar/types";

export function HeaderTitle({ children }: { children: JSX.Element | string }) {
  const isString = typeof children === "string";
  const textSize = isString && children.length > 10 ? "text-xl" : "text-2xl";

  return (
    <h1 className={`flex ${textSize} text-strong leading-none font-bold`}>
      {children}
    </h1>
  );
}
interface HeaderProps {
  user: User | null;
  page?: pageType;
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
          <div className="max-w-[200px] flex my-auto">
            <div className="mr-1 mb-auto">
              <Logo />
            </div>
            <div className="my-auto">
              {enterpriseSettings && enterpriseSettings.application_name ? (
                <div>
                  <HeaderTitle>
                    {enterpriseSettings.application_name}
                  </HeaderTitle>
                  {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && (
                    <p className="text-xs text-subtle">Powered by Danswer</p>
                  )}
                </div>
              ) : (
                <HeaderTitle>GPT Lab</HeaderTitle>
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
