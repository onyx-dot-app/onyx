import { ConnectorIndexingStatus, DocumentSet, Teamspace } from "@/lib/types";
import { TeamspaceMember } from "./TeamspaceMember";
import { TeamspaceAssistant } from "./TeamspaceAssistant";
import { TeamspaceDocumentSet } from "./TeamspaceDocumentSet";
import { TeamspaceDataSource } from "./TeamspaceDataSource";
import { Shield } from "lucide-react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { Assistant } from "@/app/admin/assistants/interfaces";
import Image from "next/image";
import { buildImgUrl } from "@/app/chat/files/images/utils";

interface TeamspaceSidebarContentProps {
  teamspace: Teamspace & { gradient: string };
  assistants: Assistant[];
  ccPairs: ConnectorIndexingStatus<any, any>[];
  documentSets: DocumentSet[];
  refreshTeamspaces: () => void;
}

export const TeamspaceSidebarContent = ({
  teamspace,
  assistants,
  ccPairs,
  documentSets,
  refreshTeamspaces,
}: TeamspaceSidebarContentProps) => {
  const { data, error } = useSWR(
    `/api/admin/token-rate-limits/teamspace/${teamspace.id}`,
    errorHandlingFetcher
  );

  const tokenRate = data && data.length > 0 ? data[0] : null;

  return (
    <>
      <div style={{ background: teamspace.gradient }} className="h-40 relative">
        <div className="absolute top-full -translate-y-1/2 left-1/2 -translate-x-1/2">
          {teamspace.logo ? (
            <div className="rounded-md w-16 h-16 bg-background overflow-hidden">
              <img
                src={buildImgUrl(teamspace.logo)}
                alt="Teamspace Logo"
                className="object-cover w-full h-full"
                width={40}
                height={40}
              />
            </div>
          ) : (
            <span
              style={{ background: teamspace.gradient }}
              className="text-3xl uppercase font-bold min-w-16 min-h-16 flex items-center justify-center rounded-xl text-inverted border-[5px] border-inverted"
            >
              {teamspace.name.charAt(0)}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-col items-center px-6 py-14 w-full">
        <div className="flex flex-col items-center">
          <h1 className="text-center font-bold text-xl md:text-[28px]">
            {teamspace.name}
          </h1>
          {/* TODO: Replace with the owner */}
          <span className="text-center text-primary pt-1 font-medium text-sm">
            {teamspace.creator.email}
          </span>
          <span className="text-center pt-4 font-bold text-sm flex items-center gap-1">
            <Shield size={16} />
            {tokenRate
              ? `${tokenRate.token_budget} Token Rate`
              : "No Token Rate"}
          </span>
        </div>

        <div className="w-full flex flex-col gap-4 pt-14">
          <TeamspaceMember
            teamspace={teamspace}
            refreshTeamspaces={refreshTeamspaces}
          />
          <TeamspaceAssistant
            teamspace={teamspace}
            assistants={assistants}
            refreshTeamspaces={refreshTeamspaces}
          />
          <TeamspaceDocumentSet
            teamspace={teamspace}
            documentSets={documentSets}
            refreshTeamspaces={refreshTeamspaces}
          />
          <TeamspaceDataSource
            teamspace={teamspace}
            ccPairs={ccPairs}
            refreshTeamspaces={refreshTeamspaces}
          />
        </div>
      </div>
    </>
  );
};