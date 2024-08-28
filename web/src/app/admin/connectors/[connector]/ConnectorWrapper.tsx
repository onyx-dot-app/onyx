"use client";

import { ValidSources } from "@/lib/types";
import AddConnector from "./AddConnectorPage";
import { FormProvider } from "@/components/context/FormContext";
import Sidebar from "./Sidebar";
import { HeaderTitle } from "@/components/header/HeaderTitle";
import { Button } from "@tremor/react";
import { isValidSource } from "@/lib/sources";

export default function ConnectorWrapper({ connector }: { connector: string }) {
  return (
    <FormProvider connector={connector}>
      <div className="flex justify-center w-full h-full">
        <Sidebar />
        <div className="mt-12 w-full max-w-3xl mx-auto">
          {!isValidSource(connector) ? (
            <div className="mx-auto flex flex-col gap-y-2">
              <HeaderTitle>
                <p>&lsquo;{connector}&lsquo; is not a valid Connector Type!</p>
              </HeaderTitle>
              <Button
                onClick={() => window.open("/admin/indexing/status", "_self")}
                className="mr-auto"
              >
                {" "}
                Go home{" "}
              </Button>
            </div>
          ) : (
            <AddConnector connector={connector as ValidSources} />
          )}
        </div>
      </div>
    </FormProvider>
  );
}
