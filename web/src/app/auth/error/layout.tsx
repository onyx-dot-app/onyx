export default function AuthErrorLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // In a production environment, you might want to send this to your error tracking service
  // For example, if using a service like Sentry:
  // captureException(new Error("Authentication error page was accessed unexpectedly"));

  return <>{children}</>;
}
