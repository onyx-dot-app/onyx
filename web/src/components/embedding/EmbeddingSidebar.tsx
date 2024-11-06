import { useEmbeddingFormContext } from "@/components/context/EmbeddingContext";
import { HeaderTitle } from "@/components/header/HeaderTitle";

import { SettingsIcon } from "@/components/icons/icons";
import { Logo } from "@/components/Logo";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Link from "next/link";
import { useContext } from "react";

export default function EmbeddingSidebar() {
  const { formStep, setFormStep, allowAdvanced, allowCreate } =
    useEmbeddingFormContext();
  const combinedSettings = useContext(SettingsContext);
  if (!combinedSettings) {
    return null;
  }
  const enterpriseSettings = combinedSettings.enterpriseSettings;

  const settingSteps = ["Embedding Model", "Reranking Model", "Advanced"];

  return (
    <div className="flex bg-background text-default">
      <div
        className={`flex-none
                  bg-background-100
                  h-screen
                  transition-all
                  bg-opacity-80
                  duration-300
                  ease-in-out
                  w-[250px]
                  `}
      >
        <div className="fixed h-full left-0 top-0 bg-background-100 w-[250px]">
          <div className="ml-4 mr-3 flex flex gap-x-1 items-center mt-2 my-auto text-text-700 text-xl">
            <div className="mr-1 my-auto h-6 w-6">
              <Logo height={24} width={24} />
            </div>

            <div>
              {enterpriseSettings && enterpriseSettings.application_name ? (
                <HeaderTitle>{enterpriseSettings.application_name}</HeaderTitle>
              ) : (
                <HeaderTitle>Danswer</HeaderTitle>
              )}
            </div>
          </div>

          <div className="mx-3 mt-6 gap-y-1 flex-col flex gap-x-1.5 items-center items-center">
            <Link
              href={"/admin/configuration/search"}
              className="w-full p-2 bg-white border-border border rounded items-center hover:bg-background-200 cursor-pointer transition-all duration-150 flex gap-x-2"
            >
              <SettingsIcon className="flex-none " />
              <p className="my-auto flex items-center text-sm">
                Search Settings
              </p>
            </Link>
          </div>

          <div className="h-full flex">
            <div className="mx-auto w-full max-w-2xl px-4 py-8">
              <div className="relative">
                <div className="absolute h-[85%] left-[6px] top-[8px] bottom-0 w-0.5 bg-gray-300"></div>
                {settingSteps.map((step, index) => {
                  return (
                    <div
                      key={index}
                      className="flex items-center mb-6 relative cursor-pointer"
                      onClick={() => {
                        setFormStep(index);
                      }}
                    >
                      <div className="flex-shrink-0 mr-4 z-10">
                        <div className="rounded-full h-3.5 w-3.5 flex items-center justify-center bg-blue-500">
                          {formStep === index && (
                            <div className="h-2 w-2 rounded-full bg-white"></div>
                          )}
                        </div>
                      </div>
                      <div
                        className={`${index <= formStep ? "text-gray-800" : "text-gray-500"}`}
                      >
                        {step}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
