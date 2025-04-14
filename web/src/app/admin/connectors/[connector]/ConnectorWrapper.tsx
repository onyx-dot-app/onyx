"use client";
import i18n from "i18next";
import k from "./../../../../i18n/keys";

import { ConfigurableSources } from "@/lib/types";
import AddConnector from "./AddConnectorPage";
import { FormProvider } from "@/components/context/FormContext";
import Sidebar from "./Sidebar";
import { HeaderTitle } from "@/components/header/HeaderTitle";
import { Button } from "@/components/ui/button";
import { isValidSource } from "@/lib/sources";

export default function ConnectorWrapper({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  return (
    <FormProvider connector={connector}>
      <div className="flex justify-center w-full h-full">
        <Sidebar />
        <div className="mt-12 w-full max-w-3xl mx-auto">
          {!isValidSource(connector) ? (
            <div className="mx-auto flex flex-col gap-y-2">
              <HeaderTitle>
                <p>
                  {i18n.t(k._7)}
                  {connector}
                  {i18n.t(k.IS_NOT_A_VALID_CONNECTOR_TYP)}
                </p>
              </HeaderTitle>
              <Button
                onClick={() => window.open("/admin/indexing/status", "_self")}
                className="mr-auto"
              >
                {" "}
                {i18n.t(k.GO_HOME)}{" "}
              </Button>
            </div>
          ) : (
            <AddConnector connector={connector} />
          )}
        </div>
      </div>
    </FormProvider>
  );
}
