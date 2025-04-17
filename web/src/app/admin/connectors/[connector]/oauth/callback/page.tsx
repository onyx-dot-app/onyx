"use client";
import i18n from "@/i18n/init";
import k from "./../../../../../../i18n/keys";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button } from "@/components/ui/button";
import Title from "@/components/ui/title";
import { KeyIcon } from "@/components/icons/icons";
import { getSourceMetadata, isValidSource } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import { handleOAuthAuthorizationResponse } from "@/lib/oauth_utils";

export default function OAuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [statusMessage, setStatusMessage] = useState("Обработка...");
  const [statusDetails, setStatusDetails] = useState(
    "Пожалуйста, подождите, пока мы завершим настройку."
  );
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [pageTitle, setPageTitle] = useState(
    "Authorize with Third-Party service"
  );

  // Extract query parameters
  const code = searchParams?.get("code");
  const state = searchParams?.get("state");

  const pathname = usePathname();
  const connector = pathname?.split("/")[3];

  useEffect(() => {
    const onFirstLoad = async () => {
      // Examples
      // connector (url segment)= "google-drive"
      // sourceType (for looking up metadata) = "google_drive"

      if (!code || !state) {
        setStatusMessage(
          "Неправильно сформированный запрос авторизации OAuth."
        );
        setStatusDetails(
          !code
            ? "Отсутствует код авторизации."
            : "Отсутствует параметр состояния."
        );
        setIsError(true);
        return;
      }

      if (!connector) {
        setStatusMessage(
          `Указанный тип источника коннектора ${connector} не существует.`
        );
        setStatusDetails(
          `${connector} не является допустимым типом источника.`
        );
        setIsError(true);
        return;
      }

      const sourceType = connector.replaceAll("-", "_");
      if (!isValidSource(sourceType)) {
        setStatusMessage(
          `Указанный тип источника коннектора ${sourceType} не существует.`
        );
        setStatusDetails(
          `${sourceType} не является допустимым типом источника.`
        );
        setIsError(true);
        return;
      }

      const sourceMetadata = getSourceMetadata(sourceType as ValidSources);
      setPageTitle(`Авторизуйтесь с помощью ${sourceMetadata.displayName}`);

      setStatusMessage("Обработка...");
      setStatusDetails("Пожалуйста, подождите, пока мы завершим авторизацию.");
      setIsError(false); // Ensure no error state during loading

      try {
        const response = await handleOAuthAuthorizationResponse(
          connector,
          code,
          state
        );

        if (!response) {
          throw new Error("Пустой ответ от сервера OAuth.");
        }

        setStatusMessage("Успешно!");
        if (response.finalize_url) {
          setRedirectUrl(response.finalize_url);
          setStatusDetails(
            `Ваша авторизация с ${sourceMetadata.displayName} успешно завершена. Для завершения настройки учетных данных требуются дополнительные шаги.`
          );
        } else {
          setRedirectUrl(response.redirect_on_success);
          setStatusDetails(
            `Ваша авторизация с ${sourceMetadata.displayName} успешно завершена.`
          );
        }
        setIsError(false);
      } catch (error) {
        console.error("OAuth ошибка:", error);
        setStatusMessage("Упс, что-то пошло не так!");
        setStatusDetails(
          "Во время процесса OAuth произошла ошибка. Попробуйте еще раз."
        );
        setIsError(true);
      }
    };

    onFirstLoad();
  }, [code, state, connector]);

  return (
    <div className="mx-auto h-screen flex flex-col">
      <AdminPageTitle title={pageTitle} icon={<KeyIcon size={32} />} />

      <div className="flex-1 flex flex-col items-center justify-center">
        <CardSection className="max-w-md w-[500px] h-[250px] p-8">
          <h1 className="text-2xl font-bold mb-4">{statusMessage}</h1>
          <p className="text-text-500">{statusDetails}</p>
          {redirectUrl && !isError && (
            <div className="mt-4">
              <p className="text-sm">
                {i18n.t(k.CLICK)}{" "}
                <a href={redirectUrl} className="text-blue-500 underline">
                  {i18n.t(k.HERE)}
                </a>{" "}
                {i18n.t(k.TO_CONTINUE)}
              </p>
            </div>
          )}
        </CardSection>
      </div>
    </div>
  );
}
