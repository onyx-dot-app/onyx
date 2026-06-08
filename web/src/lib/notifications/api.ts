async function handleNotificationMutation(
  response: Response,
  fallbackMessage: string
): Promise<void> {
  if (response.ok) {
    return;
  }

  const error = await response.json().catch(() => ({}));
  throw new Error(error.detail || fallbackMessage);
}

export async function dismissNotification(
  notificationId: number,
  expectedLastShown?: string
): Promise<void> {
  const body = expectedLastShown
    ? {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_last_shown: expectedLastShown }),
      }
    : {};
  const response = await fetch(`/api/notifications/${notificationId}/dismiss`, {
    method: "POST",
    ...body,
  });
  return handleNotificationMutation(response, "Failed to dismiss notification");
}

export async function dismissAllNotifications(): Promise<void> {
  const response = await fetch("/api/notifications/dismiss-all", {
    method: "POST",
  });
  return handleNotificationMutation(
    response,
    "Failed to dismiss notifications"
  );
}
