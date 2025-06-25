"use client";

import { ErrorCallout } from "@/components/ErrorCallout";
import {
  useConnectorCredentialIndexingStatus,
  useUserGroups,
} from "@/lib/hooks";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { BookmarkIcon } from "@/components/icons/icons";
import { BackButton } from "@/components/BackButton";
import { Card } from "@tremor/react";

import { useRouter } from "next/navigation";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useKnowledgeMaps } from "../hooks";
import { KnowledgeMapCreationForm } from "../new/KnowledgeMapCreationForm";
import { useDocumentSets } from "../../sets/hooks";
import { use } from "react";

function Main({ knowledgeMapId }: { knowledgeMapId: number }) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const {
    data: knowledgeMaps,
    isLoading: isKnowledgeMapsLoading,
    error: knowledgeMapsError,
    refreshKnowledgeMaps,
  } = useKnowledgeMaps();

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useDocumentSets();

  // EE only
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();

  if (isKnowledgeMapsLoading || userGroupsIsLoading) {
    return <ThreeDotsLoader />;
  }

  if (knowledgeMapsError || ccPairsError || !ccPairs) {
    return (
      <ErrorCallout
        errorTitle="Не удалось получить карту знаний"
        errorMsg={knowledgeMapsError}
      />
    );
  }

  console.log({ knowledgeMapId });
  const knowledgeMap = knowledgeMaps?.find(
    (knowledgeMap) => knowledgeMap.id === knowledgeMapId
  );
  if (!knowledgeMap) {
    return (
      <ErrorCallout
        errorTitle="Карта знаний не найдена"
        errorMsg={`Карта знаний с идентификатором ${knowledgeMapId} не найдена`}
      />
    );
  }

  return (
    <div>
      {popup}

      <AdminPageTitle
        icon={<BookmarkIcon size={32} />}
        title={knowledgeMap.name}
      />

      <Card>
        <KnowledgeMapCreationForm
          // @ts-ignore
          ccPairs={ccPairs.sort((a, b) => a.id - b.id)}
          userGroups={userGroups}
          onClose={() => {
            refreshKnowledgeMaps();
            router.push("/admin/documents/knowledge_maps");
          }}
          setPopup={setPopup}
          existingDocumentSet={knowledgeMap}
        />
      </Card>
    </div>
  );
}

export default function Page(props: {
  params: Promise<{ knowledgeMapId: string }>;
}) {
  const params = use(props.params);
  const { knowledgeMapId } = params;

  if (!knowledgeMapId || typeof knowledgeMapId !== "string") {
    return (
      <ErrorCallout
        errorTitle="Неверный идентификатор карты знаний"
        errorMsg="Идентификатор карты знаний должен быть строкой."
      />
    );
  }

  const knowledgeMapIdNumber = parseInt(knowledgeMapId);

  if (isNaN(knowledgeMapIdNumber)) {
    return (
      <ErrorCallout
        errorTitle="Неверный идентификатор карты знаний"
        errorMsg={`Идентификатор карты знаний "${knowledgeMapId}" не является числом.`}
      />
    );
  }

  return (
    <div>
      <BackButton />
      <Main knowledgeMapId={knowledgeMapIdNumber} />
    </div>
  );
}
