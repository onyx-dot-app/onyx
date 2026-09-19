import { useMemo, useState } from "react";
import { View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";

import { useAgents } from "@/api/chat/agents";
import { AgentCard } from "@/components/agents/AgentCard";
import { SettingsLayout } from "@/components/settings/SettingsLayout";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import { TextInput } from "@/components/ui/text-input";
import { MinimalAgent, splitAgentsForGallery } from "@/chat/agents";
import { useSelectAgent } from "@/hooks/useLiveAgent";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import SvgSearch from "@/icons/search";
import SvgX from "@/icons/x";

export default function AgentsScreen() {
  const { agents, isLoading, isError } = useAgents();
  const selectAgent = useSelectAgent();
  const [search, setSearch] = useState("");

  const { featured, all } = useMemo(
    () => splitAgentsForGallery(agents, search),
    [agents, search],
  );
  const total = featured.length + all.length;

  // Keep loading/error distinct from a genuinely empty result.
  const statusMessage = isLoading
    ? "Loading agents…"
    : isError
      ? "Couldn't load agents."
      : total === 0
        ? "No agents found"
        : null;

  return (
    <SafeAreaView edges={["top"]} className="flex-1 bg-background-neutral-00">
      {/* SettingsLayout omits a back button; the (app) stack is headerless */}
      <View className="flex-row items-center px-4 py-12">
        <Button
          prominence="internal"
          icon={SvgX}
          accessibilityLabel="Close agents"
          onPress={() => router.back()}
        />
      </View>

      <SettingsLayout.Root keyboardShouldPersistTaps="handled">
        <SettingsLayout.Header
          icon={SvgOnyxOctagon}
          title="Agents"
          description="Pick an agent to start a chat."
        >
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Search agents…"
            leftIcon={SvgSearch}
            clearButton
            autoCapitalize="none"
            autoCorrect={false}
          />
        </SettingsLayout.Header>

        <SettingsLayout.Body>
          {statusMessage ? (
            <Text
              font="secondary-body"
              color="text-03"
              className="py-24 text-center"
            >
              {statusMessage}
            </Text>
          ) : null}
          {featured.length > 0 ? (
            <AgentSection
              title="Featured Agents"
              description="Curated by your team"
              agents={featured}
              onSelect={selectAgent}
            />
          ) : null}
          {all.length > 0 ? (
            <AgentSection
              title="All Agents"
              agents={all}
              onSelect={selectAgent}
            />
          ) : null}
        </SettingsLayout.Body>
      </SettingsLayout.Root>
    </SafeAreaView>
  );
}

interface AgentSectionProps {
  title: string;
  description?: string;
  agents: MinimalAgent[];
  onSelect: (agent: MinimalAgent) => void;
}

function AgentSection({
  title,
  description,
  agents,
  onSelect,
}: AgentSectionProps) {
  return (
    <View className="gap-8">
      <View>
        <Text font="heading-h3" color="text-05">
          {title}
        </Text>
        {description ? (
          <Text font="secondary-body" color="text-03">
            {description}
          </Text>
        ) : null}
      </View>
      {agents.map((agent) => (
        <AgentCard key={agent.id} agent={agent} onPress={onSelect} />
      ))}
    </View>
  );
}
