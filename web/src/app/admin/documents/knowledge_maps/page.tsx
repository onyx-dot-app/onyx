"use client";

import i18n from "@/i18n/init";
import k from "../../../../i18n/keys";
import { AdminPageTitle } from "@/components/admin/Title";
import { DeleteButton } from "@/components/DeleteButton";
import { BookOpen } from "@/components/icons/icons";
import {
  Button,
  Text,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  Title,
} from "@tremor/react";
import Link from "next/link";

import { useState } from "react";
import { useKnowledgeMaps } from "./hooks";
import { deleteKnowledgeMap } from "./lib";
import { usePopup } from "@/components/admin/connectors/Popup";
import { EditRow } from "./editRow";
import { useDocumentSets } from "../sets/hooks";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
const numToDisplay = 50;

const Page = () => {
  const { popup, setPopup } = usePopup();

  const {
    data: knowledgeMaps,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
    refreshKnowledgeMaps,
  } = useKnowledgeMaps();

  const [page, setPage] = useState(1);

  const {
    data: documentSets,
    isLoading: isDocumentSetsLoading,
    error: documentSetsError,
    refreshDocumentSets,
  } = useDocumentSets();

  console.log(knowledgeMaps);
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<BookOpen size={32} />}
        title={i18n.t(k.KNOWLEDGE_MAPS)}
      />

      <Text className="mb-3">
        <b>{i18n.t(k.KNOWLEDGE_MAP)}</b> {i18n.t(k.KNOWLEDGE_MAP_DESCRIPTION)}
      </Text>

      <div className="mb-3"></div>

      <div className="flex mb-6">
        <Link href="/admin/documents/knowledge_maps/new">
          <Button size="xs" color="green" className="ml-2 my-auto">
            {i18n.t(k.CREATE_KNOWLEDGE_MAP)}
          </Button>
        </Link>
      </div>

      {!!knowledgeMaps?.length && (
        <div>
          <Title>{i18n.t(k.EXISTING_KNOWLEDGE_MAPS)}</Title>
          <Table className="overflow-visible mt-2">
            <TableHead>
              <TableRow>
                <TableHeaderCell>{i18n.t(k.TITLE)}</TableHeaderCell>
                <TableHeaderCell>{i18n.t(k.CONNECTORS)}</TableHeaderCell>
                <TableHeaderCell>{i18n.t(k.DELETE)}</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {knowledgeMaps
                ?.slice((page - 1) * numToDisplay, page * numToDisplay)
                .map((knowledgeMap) => {
                  const documentSet = documentSets?.find(
                    (d) => d.id === knowledgeMap.document_set_id
                  );
                  return (
                    <TableRow key={knowledgeMap.id}>
                      <TableCell className="whitespace-normal break-all">
                        <div className="flex gap-x-1 text-emphasis">
                          <EditRow knowledgeMap={knowledgeMap} />
                        </div>
                      </TableCell>
                      <TableCell>
                        {documentSet?.cc_pair_descriptors.map(
                          (ccPairDescriptor, ind) => {
                            return (
                              <div
                                className={
                                  ind !==
                                  documentSet.cc_pair_descriptors.length - 1
                                    ? "mb-3"
                                    : ""
                                }
                                key={ccPairDescriptor.id}
                              >
                                <ConnectorTitle
                                  connector={ccPairDescriptor.connector}
                                  ccPairName={ccPairDescriptor.name}
                                  ccPairId={ccPairDescriptor.id}
                                  showMetadata={false}
                                />
                              </div>
                            );
                          }
                        )}
                      </TableCell>
                      <TableCell>
                        <DeleteButton
                          onClick={async () => {
                            const response = await deleteKnowledgeMap(
                              knowledgeMap.id
                            );
                            if (response.ok) {
                              setPopup({
                                message: `${i18n.t(k.KNOWLEDGE_MAP)} "${
                                  knowledgeMap.name
                                }" ${i18n.t(k.KNOWLEDGE_MAP_DELETION_SUCCESS)}`,
                                type: "success",
                              });
                            } else {
                              const errorMsg = (await response.json()).detail;
                              setPopup({
                                message: `${i18n.t(
                                  k.KNOWLEDGE_MAP_DELETION_FAILED
                                )} ${errorMsg}`,
                                type: "error",
                              });
                            }
                            refreshKnowledgeMaps();
                          }}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
};

export default Page;
