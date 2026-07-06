import { useState } from "react";
import { ScrollView, View } from "react-native";
import Animated, {
  FadeIn,
  FadeOut,
  LinearTransition,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";
import { KeyboardStickyView } from "react-native-keyboard-controller";
import { router } from "expo-router";

import { ChatHeader } from "@/components/chat/ChatHeader";
import { InputBar } from "@/components/chat/InputBar";
import { MessageList } from "@/components/chat/MessageList";
import { ProjectContextPanel } from "@/components/chat/ProjectContextPanel";
import { ProjectChatSessionList } from "@/components/chat/ProjectChatSessionList";
import { useProjectDetails } from "@/api/chat/projects";
import { useAgents } from "@/api/chat/agents";
import { useChatController } from "@/hooks/useChatController";

interface ProjectViewProps {
  projectId: number | null;
}

const TRANSITION_MS = 150;

// Project detail + chat (mirrors web's AppPage). The first send transitions in
// place — input slides down, panel/list fade — instead of navigating, so it's smooth.
export function ProjectView({ projectId }: ProjectViewProps) {
  // set on first send; drives the project→chat swap
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const started = activeSessionId != null;

  const { data: details, isLoading } = useProjectDetails(projectId);
  const { agents } = useAgents();
  const { messages, input, setInput, submit, stop, chatState } =
    useChatController(
      activeSessionId,
      undefined,
      projectId,
      setActiveSessionId,
    );

  const chats = details?.project?.chat_sessions ?? [];

  return (
    <SafeAreaView edges={["top"]} className="flex-1 bg-background-neutral-00">
      <ChatHeader title={details?.project?.name} />

      <View className="flex-1">
        {started ? (
          <Animated.View
            key="messages"
            entering={FadeIn.duration(TRANSITION_MS)}
            className="flex-1"
          >
            <MessageList messages={messages} />
          </Animated.View>
        ) : (
          <Animated.View
            key="context"
            exiting={FadeOut.duration(TRANSITION_MS)}
            className="max-h-[50%]"
          >
            <ScrollView keyboardShouldPersistTaps="handled">
              <View className="gap-24 px-24 pb-8 pt-8">
                <ProjectContextPanel details={details} isLoading={isLoading} />
              </View>
            </ScrollView>
          </Animated.View>
        )}

        <KeyboardStickyView>
          <Animated.View layout={LinearTransition.duration(TRANSITION_MS)}>
            <InputBar
              value={input}
              onChangeText={setInput}
              onSend={() => {
                void submit();
              }}
              onStop={stop}
              chatState={chatState}
            />
          </Animated.View>
        </KeyboardStickyView>

        {!started ? (
          <Animated.View
            key="chats"
            exiting={FadeOut.duration(TRANSITION_MS)}
            className="flex-1"
          >
            <ScrollView keyboardShouldPersistTaps="handled">
              <View className="px-24 pb-24 pt-8">
                <ProjectChatSessionList
                  chats={chats}
                  agents={agents}
                  personaIdToFeatured={
                    details?.persona_id_to_is_featured ?? undefined
                  }
                  isLoading={isLoading && !details}
                  onSelect={(sessionId) =>
                    router.navigate({
                      pathname: "/chat/[id]",
                      params: { id: sessionId },
                    })
                  }
                />
              </View>
            </ScrollView>
          </Animated.View>
        ) : null}
      </View>
    </SafeAreaView>
  );
}
