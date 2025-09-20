"use client";

import React from "react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Users, Key, MessageSquare } from "lucide-react";
import { UserTypeFilter } from "@/lib/userUtils";

interface UserTypeToggleProps {
  filters: UserTypeFilter;
  onFiltersChange: (filters: UserTypeFilter) => void;
  userCounts?: {
    slackUsers: number;
    apiKeys: number;
    totalUsers: number;
  };
}

export const UserTypeToggle: React.FC<UserTypeToggleProps> = ({
  filters,
  onFiltersChange,
  userCounts,
}) => {
  const handleSlackToggle = (checked: boolean) => {
    onFiltersChange({
      ...filters,
      showSlackUsers: checked,
    });
  };

  const handleApiKeyToggle = (checked: boolean) => {
    onFiltersChange({
      ...filters,
      showApiKeys: checked,
    });
  };

  return (
    <Card className="mb-4">
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-foreground">User Type Filters</h3>
          <div className="text-xs text-muted-foreground">
            {userCounts && (
              <span>
                Showing{" "}
                {userCounts.totalUsers -
                  (!filters.showSlackUsers ? userCounts.slackUsers : 0) -
                  (!filters.showApiKeys ? userCounts.apiKeys : 0)}{" "}
                of {userCounts.totalUsers} users
              </span>
            )}
          </div>
        </div>
        
        <div className="space-y-4">
          <div className="flex items-center justify-between space-x-3">
            <div className="flex items-center space-x-3">
              <MessageSquare className="h-4 w-4 text-blue-500" />
              <div className="flex flex-col">
                <Label htmlFor="slack-toggle" className="text-sm font-medium">
                  Slack Users
                </Label>
                <p className="text-xs text-muted-foreground">
                  Users who access Onyx through Slack
                  {userCounts && ` (${userCounts.slackUsers})`}
                </p>
              </div>
            </div>
            <Switch
              id="slack-toggle"
              checked={filters.showSlackUsers}
              onCheckedChange={handleSlackToggle}
            />
          </div>

          <div className="flex items-center justify-between space-x-3">
            <div className="flex items-center space-x-3">
              <Key className="h-4 w-4 text-green-500" />
              <div className="flex flex-col">
                <Label htmlFor="api-key-toggle" className="text-sm font-medium">
                  API Keys
                </Label>
                <p className="text-xs text-muted-foreground">
                  Programmatic access keys
                  {userCounts && ` (${userCounts.apiKeys})`}
                </p>
              </div>
            </div>
            <Switch
              id="api-key-toggle"
              checked={filters.showApiKeys}
              onCheckedChange={handleApiKeyToggle}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
};