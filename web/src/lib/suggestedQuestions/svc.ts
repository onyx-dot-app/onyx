/** Marks a suggested question clicked, so the person is not shown it again. */
export async function markSuggestedQuestionUsed(
  questionId: string
): Promise<void> {
  const res = await fetch("/api/chat/suggested-questions/used", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question_id: questionId }),
  });
  if (!res.ok) {
    throw new Error("Failed to mark the suggested question used");
  }
}
