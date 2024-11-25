"use client";

import { Logo } from "@/components/EEA_Logo";
import { Logo_empty } from "@/components/EEA_Logo";
import { HeaderTitle } from "@/components/header/HeaderTitle";
//import { Logo } from "@/components/Logo";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED } from "@/lib/constants";
import Link from "next/link";
import { useContext } from "react";
import { FiSidebar } from "react-icons/fi";

export default function FixedLogo({
  // Whether the sidebar is toggled or not
  backgroundToggled,
}: {
  backgroundToggled?: boolean;
}) {
  const combinedSettings = useContext(SettingsContext);
  const settings = combinedSettings?.settings;
  const enterpriseSettings = combinedSettings?.enterpriseSettings;

  return (
    <>
      <Link
        href={
          settings && settings.default_page === "chat" ? "/chat" : "/search"
        }
        className="fixed cursor-pointer flex z-40 left-2.5 top-2"
      >
        <div className="max-w-[185px] mobile:hidden flex items-center gap-x-1 my-auto">
          <div className="flex-none my-auto">
            <Logo height={24} width={80} />
          </div>
          <div className="w-full">
            {enterpriseSettings && enterpriseSettings.application_name ? (
              <div>
                <HeaderTitle backgroundToggled={backgroundToggled}>
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
      <div className="mobile:hidden fixed left-2.5 bottom-4">
        <FiSidebar />
      </div>
    </>
  );
}
