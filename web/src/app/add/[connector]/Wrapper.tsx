"use client";

import { ChatSession } from "@/app/chat/interfaces";
import { User, ValidSources } from "@/lib/types";
import SidebarWrapper from "@/app/assistants/SidebarWrapper";
import AddConnector from "./AddConnectorPage";
import { useState } from "react";
import { FormProvider } from "@/components/context/FormContext";
import { SourceCategory } from "@/lib/search/interfaces";

export default function WrappedPage({
  initiallyToggled,
  connector,
  user,
}: {
  connector: string;
  initiallyToggled: boolean;
  user: User | null;
}) {
  const [index, setIndex] = useState(1);

  const increment = () => {
    setIndex((index) => index + 1);
  };
  const decrement = () => {
    setIndex((index) => index - 1);
  };

  return (
    <FormProvider>
      <SidebarWrapper
        adminSetupProps={{
          steps: ["Credentials", "Channel", "Finalize"],
          index: index - 1,
          max_index: index - 1,
        }}
        page="admin"
        initiallyToggled={initiallyToggled}
        headerProps={{ user, page: "admin" }}
        contentProps={{
          index,
          increment,
          decrement,
        }}
        content={(contentProps) => (
          <AddConnector connector={connector as ValidSources} />
        )}
      />
    </FormProvider>
  );
}
