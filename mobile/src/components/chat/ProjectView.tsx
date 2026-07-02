import { ScrollView, View } from "react-native";
import { router } from "expo-router";

import { ChatScreen } from "@/components/chat/ChatScreen";
import { InputBar } from "@/components/chat/InputBar";
import { ProjectContextPanel } from "@/components/chat/ProjectContextPanel";
import { ProjectChatSessionList } from "@/components/chat/ProjectChatSessionList";
import { useProjectDetails } from "@/api/chat/projects";
import { useChatController } from "@/hooks/useChatController";

interface ProjectViewProps {
  projectId: number | null;
}

// Context panel + chats, with a project-scoped input bar. Input sticks to the
// bottom (web keeps it mid-page).
export function ProjectView({ projectId }: ProjectViewProps) {
  const { data: details, isLoading } = useProjectDetails(projectId);
  const { input, setInput, submit, stop, chatState } = useChatController(
    null,
    undefined,
    projectId,
  );

  const chats = details?.project?.chat_sessions ?? [];

  return (
    <ChatScreen
      title={details?.project?.name}
      input={
        <InputBar
          value={input}
          onChangeText={setInput}
          onSend={() => {
            void submit();
          }}
          onStop={stop}
          chatState={chatState}
        />
      }
    >
      <ScrollView className="flex-1" keyboardShouldPersistTaps="handled">
        <View className="gap-24 px-24 pb-24 pt-8">
          <ProjectContextPanel details={details} isLoading={isLoading} />
          <ProjectChatSessionList
            chats={chats}
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
    </ChatScreen>
  );
}
