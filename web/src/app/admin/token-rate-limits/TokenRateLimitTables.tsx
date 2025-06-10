"use client";

import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import Title from "@/components/ui/title";
import { DeleteButton } from "@/components/DeleteButton";
import { deleteTokenRateLimit, updateTokenRateLimit } from "./lib";
import { ThreeDotsLoader } from "@/components/Loading";
import { TokenRateLimitDisplay } from "./types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { CustomCheckbox } from "@/components/CustomCheckbox";
import { TableHeader } from "@/components/ui/table";
import Text from "@/components/ui/text";

type TokenRateLimitTableArgs = {
  tokenRateLimits: TokenRateLimitDisplay[];
  title?: string;
  description?: string;
  fetchUrl: string;
  hideHeading?: boolean;
  isAdmin: boolean;
};

export const TokenRateLimitTable = ({
  tokenRateLimits,
  title,
  description,
  fetchUrl,
  hideHeading,
  isAdmin,
}: TokenRateLimitTableArgs) => {
  const shouldRenderGroupName = () =>
    tokenRateLimits.length > 0 &&
    tokenRateLimits[0] !== undefined &&
    tokenRateLimits[0].group_name !== undefined;

  const handleEnabledChange = (id: number) => {
    const tokenRateLimit = tokenRateLimits.find(
      (tokenRateLimit) => tokenRateLimit.token_id === id
    );

    if (!tokenRateLimit) {
      return;
    }

    updateTokenRateLimit(id, {
      token_budget: tokenRateLimit.token_budget,
      period_hours: tokenRateLimit.period_hours,
      enabled: !tokenRateLimit.enabled,
    }).then(() => {
      mutate(fetchUrl);
    });
  };

  const handleDelete = (id: number) =>
    deleteTokenRateLimit(id).then(() => {
      mutate(fetchUrl);
    });

  if (tokenRateLimits.length === 0) {
    return (
      <div>
        {!hideHeading && title && <Title>{title}</Title>}
        {!hideHeading && description && (
          <Text className="my-2">{description}</Text>
        )}
        <Text className={`${!hideHeading && "my-8"}`}>
          No token rate limits set!
        </Text>
      </div>
    );
  }

  return (
    <div>
      {!hideHeading && title && <Title>{title}</Title>}
      {!hideHeading && description && (
        <Text className="my-2">{description}</Text>
      )}
      <Table
        className={`overflow-visible ${
          !hideHeading && "my-8"
        } [&_td]:text-center [&_th]:text-center`}
      >
        <TableHeader>
          <TableRow>
            <TableHead>Enabled</TableHead>
            {shouldRenderGroupName() && <TableHead>Group Name</TableHead>}
            <TableHead>Time Window (Hours)</TableHead>
            <TableHead>Token Budget (Thousands)</TableHead>
            {isAdmin && <TableHead>Delete</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {tokenRateLimits.map((tokenRateLimit) => {
            return (
              <TableRow key={tokenRateLimit.token_id}>
                <TableCell>
                  <div className="flex justify-center">
                    <div
                      onClick={
                        isAdmin
                          ? () => handleEnabledChange(tokenRateLimit.token_id)
                          : undefined
                      }
                      className={`px-1 py-0.5 rounded select-none w-24 ${
                        isAdmin
                          ? "hover:bg-accent-background cursor-pointer"
                          : "opacity-50"
                      }`}
                    >
                      <div className="flex items-center justify-center">
                        <CustomCheckbox
                          checked={tokenRateLimit.enabled}
                          onChange={
                            isAdmin
                              ? () =>
                                  handleEnabledChange(tokenRateLimit.token_id)
                              : undefined
                          }
                        />
                        <p className="ml-2">
                          {tokenRateLimit.enabled ? "Enabled" : "Disabled"}
                        </p>
                      </div>
                    </div>
                  </div>
                </TableCell>
                {shouldRenderGroupName() && (
                  <TableCell className="font-bold text-text-darker">
                    {tokenRateLimit.group_name}
                  </TableCell>
                )}
                <TableCell>
                  {tokenRateLimit.period_hours +
                    " hour" +
                    (tokenRateLimit.period_hours > 1 ? "s" : "")}
                </TableCell>
                <TableCell>
                  {tokenRateLimit.token_budget + " thousand tokens"}
                </TableCell>
                {isAdmin && (
                  <TableCell>
                    <div className="flex justify-center">
                      <DeleteButton
                        onClick={() => handleDelete(tokenRateLimit.token_id)}
                      />
                    </div>
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
};

export const GenericTokenRateLimitTable = ({
  fetchUrl,
  title,
  description,
  hideHeading,
  responseMapper,
  isAdmin = true,
}: {
  fetchUrl: string;
  title?: string;
  description?: string;
  hideHeading?: boolean;
  responseMapper?: (data: any) => TokenRateLimitDisplay[];
  isAdmin?: boolean;
}) => {
  const { data, isLoading, error } = useSWR<TokenRateLimitDisplay[]>(
    fetchUrl,
    errorHandlingFetcher
  );

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (!isLoading && error) {
    return <Text>Failed to load token rate limits</Text>;
  }

  let processedData = data;
  if (responseMapper) {
    processedData = responseMapper(data);
  }

  return (
    <TokenRateLimitTable
      tokenRateLimits={processedData ?? []}
      fetchUrl={fetchUrl}
      title={title}
      description={description}
      hideHeading={hideHeading}
      isAdmin={isAdmin}
    />
  );
};
