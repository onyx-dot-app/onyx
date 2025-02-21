import { useFormContext } from "@/components/context/FormContext";
import { HeaderTitle } from "@/components/header/HeaderTitle";

import { SettingsIcon } from "@/components/icons/icons";
import { Logo } from "@/components/logo/Logo";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { credentialTemplates } from "@/lib/connectors/credentials";
import Link from "next/link";
import { useUser } from "@/components/user/UserProvider";
import { useContext } from "react";
import { User } from "@/lib/types";

function BackButton({
  isAdmin,
  isCurator,
  user,
}: {
  isAdmin: boolean;
  isCurator: boolean;
  user: User | null;
}) {
  const buttonText = isAdmin ? "Admin Page" : "Curator Page";

  if (!isAdmin && !isCurator) {
    console.error(
      `User is neither admin nor curator, defaulting to curator view. Found user:\n ${JSON.stringify(
        user,
        null,
        2
      )}`
    );
  }

  return (
    <div className="mx-3 mt-6 flex-col flex items-center">
      <Link
        href={"/admin/add-connector"}
        className="w-full p-2 bg-white border-border border rounded items-center hover:bg-background-200 cursor-pointer transition-all duration-150 flex gap-x-2"
      >
        <SettingsIcon className="flex-none " />
        <p className="my-auto flex items-center text-sm">{buttonText}</p>
      </Link>
    </div>
  );
}

export default function Sidebar() {
  const { formStep, setFormStep, connector, allowAdvanced, allowCreate } =
    useFormContext();
  const combinedSettings = useContext(SettingsContext);
  const { isCurator, isAdmin, user } = useUser();
  if (!combinedSettings) {
    return null;
  }
  const enterpriseSettings = combinedSettings.enterpriseSettings;
  const noCredential = credentialTemplates[connector] == null;

  const settingSteps = [
    ...(!noCredential ? ["Credential"] : []),
    "Connector",
    ...(connector == "file" ? [] : ["Advanced (optional)"]),
  ];

  return (
    <div className="flex flex-none w-[250px] text-default">
      <div
        className={`
                  fixed
                  bg-background-sidebar
                  h-screen
                  transition-all
                  bg-opacity-80
                  duration-300
                  ease-in-out
                  w-[250px]
                  `}
      >
        <div className="fixed h-full left-0 top-0 w-[250px]">
          <div className="ml-4 mr-3 flex flex gap-x-1 items-center mt-2 my-auto text-text-700 text-xl">
            <div className="mr-1 my-auto h-6 w-6">
              <Logo height={24} width={24} />
            </div>

            <div>
              {enterpriseSettings && enterpriseSettings.application_name ? (
                <HeaderTitle>{enterpriseSettings.application_name}</HeaderTitle>
              ) : (
                <HeaderTitle>Onyx</HeaderTitle>
              )}
            </div>
          </div>

          <BackButton isAdmin={isAdmin} isCurator={isCurator} user={user} />

          <div className="h-full flex">
            <div className="mx-auto w-full max-w-2xl px-4 py-8">
              <div className="relative">
                {connector != "file" && (
                  <div className="absolute h-[85%] left-[6px] top-[8px] bottom-0 w-0.5 bg-background-300"></div>
                )}
                {settingSteps.map((step, index) => {
                  const allowed =
                    (step == "Connector" && allowCreate) ||
                    (step == "Advanced (optional)" && allowAdvanced) ||
                    index <= formStep;

                  return (
                    <div
                      key={index}
                      className={`flex items-center mb-6 relative ${
                        !allowed ? "cursor-not-allowed" : "cursor-pointer"
                      }`}
                      onClick={() => {
                        if (allowed) {
                          setFormStep(index - (noCredential ? 1 : 0));
                        }
                      }}
                    >
                      <div className="flex-shrink-0 mr-4 z-10">
                        <div
                          className={`rounded-full h-3.5 w-3.5 flex items-center justify-center ${
                            allowed ? "bg-blue-500" : "bg-background-300"
                          }`}
                        >
                          {formStep === index && (
                            <div className="h-2 w-2 rounded-full bg-white"></div>
                          )}
                        </div>
                      </div>
                      <div
                        className={`${
                          index <= formStep ? "text-text-800" : "text-text-500"
                        }`}
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
