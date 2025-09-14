"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../../i18n/keys";
import { use } from "react";

import { GroupsIcon } from "@/components/icons/icons";
import { GroupDisplay } from "./GroupDisplay";
import { useSpecificUserGroup } from "./hook";
import { ThreeDotsLoader } from "@/components/Loading";
import {
  useConnectorCredentialIndexingStatus,
  useConnectorStatus,
  useUsers,
} from "@/lib/hooks";
import { useRouter } from "next/navigation";
import { BackButton } from "@/components/BackButton";
import { AdminPageTitle } from "@/components/admin/Title";

const Page = (props: { params: Promise<{ groupId: string }> }) => {
  const { t } = useTranslation();
  const params = use(props.params);
  const router = useRouter();

  const {
    userGroup,
    isLoading: userGroupIsLoading,
    error: userGroupError,
    refreshUserGroup,
  } = useSpecificUserGroup(params.groupId);
  const {
    data: users,
    isLoading: userIsLoading,
    error: usersError,
  } = useUsers({ includeApiKeys: true });
  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorStatus();

  if (userGroupIsLoading || userIsLoading || isCCPairsLoading) {
    return (
      <div className="h-full">
        <div className="my-auto">
          <ThreeDotsLoader />
        </div>
      </div>
    );
  }

  if (!userGroup || userGroupError) {
    return <div>{t(k.ERROR_LOADING_USER_GROUP)}</div>;
  }
  if (!users || usersError) {
    return <div>{t(k.ERROR_LOADING_USERS)}</div>;
  }
  if (!ccPairs || ccPairsError) {
    return <div>{t(k.ERROR_LOADING_CONNECTORS)}</div>;
  }

  return (
    <div className="mx-auto container">
      <BackButton />

      <AdminPageTitle
        title={userGroup.name || t(k.UNKNOWN_USER)}
        icon={<GroupsIcon size={32} />}
      />

      {userGroup ? (
        <GroupDisplay
          users={users.accepted}
          ccPairs={ccPairs}
          userGroup={userGroup}
          refreshUserGroup={refreshUserGroup}
        />
      ) : (
        <div>{t(k.UNABLE_TO_FETCH_USER_GROUP)}</div>
      )}
    </div>
  );
};

export default Page;
