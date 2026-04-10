"use client";

import { useEffect } from "react";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { useRulesets } from "@/app/proposal-review/hooks/useRulesets";
import { useProposalReviewContext } from "@/app/proposal-review/contexts/ProposalReviewContext";
import { Text } from "@opal/components";

export default function RulesetSelector() {
  const { rulesets, defaultRuleset, isLoading } = useRulesets();
  const { selectedRulesetId, setSelectedRulesetId } =
    useProposalReviewContext();

  // Auto-select the default ruleset on first load
  useEffect(() => {
    if (!selectedRulesetId && defaultRuleset) {
      setSelectedRulesetId(defaultRuleset.id);
    }
  }, [defaultRuleset, selectedRulesetId, setSelectedRulesetId]);

  if (isLoading) {
    return (
      <Text font="secondary-body" color="text-03">
        Loading rulesets...
      </Text>
    );
  }

  if (rulesets.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        No rulesets available
      </Text>
    );
  }

  return (
    <InputSelect
      value={selectedRulesetId ?? undefined}
      onValueChange={setSelectedRulesetId}
    >
      <InputSelect.Trigger placeholder="Select ruleset" />
      <InputSelect.Content>
        {rulesets.map((ruleset) => (
          <InputSelect.Item key={ruleset.id} value={ruleset.id}>
            {ruleset.name}
          </InputSelect.Item>
        ))}
      </InputSelect.Content>
    </InputSelect>
  );
}
