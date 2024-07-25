"use client";

import {
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
  Title,
  Text,
} from "@tremor/react";
import { DeleteButton } from "@/components/DeleteButton";
import { deleteTokenRateLimit, updateTokenRateLimit } from "./lib";
import { ThreeDotsLoader } from "@/components/Loading";
import { TokenRateLimitDisplay } from "./types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { CustomCheckbox } from "@/components/CustomCheckbox";

type TokenRateLimitTableArgs = {
  tokenRateLimits: TokenRateLimitDisplay[];
  title?: string;
  description?: string;
  fetchUrl: string;
  hideHeading?: boolean;
};

export const TokenRateLimitTable = ({
  tokenRateLimits,
  title,
  description,
  fetchUrl,
  hideHeading,
}: TokenRateLimitTableArgs) => {
  const shouldRenderGroupName = () =>
    tokenRateLimits.length > 0 && tokenRateLimits[0].group_name !== undefined;

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
      <Table className={`overflow-visible ${!hideHeading && "my-8"}`}>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Enabled</TableHeaderCell>
            {shouldRenderGroupName() && (
              <TableHeaderCell>Group Name</TableHeaderCell>
            )}
            <TableHeaderCell>Time Window (Hours)</TableHeaderCell>
            <TableHeaderCell>Token Budget (Thousands)</TableHeaderCell>
            <TableHeaderCell>Delete</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {tokenRateLimits.map((tokenRateLimit) => {
            return (
              <TableRow key={tokenRateLimit.token_id}>
                <TableCell>
                  <div
                    onClick={() => handleEnabledChange(tokenRateLimit.token_id)}
                    className="px-1 py-0.5 hover:bg-hover-light rounded flex cursor-pointer select-none w-24 flex"
                  >
                    <div className="mx-auto flex">
                      <CustomCheckbox checked={tokenRateLimit.enabled} />
                      <p className="ml-2">
                        {tokenRateLimit.enabled ? "Enabled" : "Disabled"}
                      </p>
                    </div>
                  </div>
                </TableCell>
                {shouldRenderGroupName() && (
                  <TableCell className="font-bold text-emphasis">
                    {tokenRateLimit.group_name}
                  </TableCell>
                )}
                <TableCell>{tokenRateLimit.period_hours}</TableCell>
                <TableCell>{tokenRateLimit.token_budget}</TableCell>
                <TableCell>
                  <DeleteButton
                    onClick={() => handleDelete(tokenRateLimit.token_id)}
                  />
                </TableCell>
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
}: {
  fetchUrl: string;
  title?: string;
  description?: string;
  hideHeading?: boolean;
  responseMapper?: (data: any) => TokenRateLimitDisplay[];
}) => {
  const { data, isLoading, error } = useSWR(fetchUrl, errorHandlingFetcher);

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
      tokenRateLimits={processedData}
      fetchUrl={fetchUrl}
      title={title}
      description={description}
      hideHeading={hideHeading}
    />
  );
};
