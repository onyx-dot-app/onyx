"use client";
import { redirect } from "next/navigation";
import { useEffect } from "react";

export default function AnonymousPage({
  anonymousPath,
}: {
  anonymousPath: string;
}) {
  const loginAsAnonymousUser = async () => {
    try {
      const response = await fetch(
        `/api/tenants/anonymous-user?anonymous_user_path=${encodeURIComponent(
          anonymousPath
        )}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "same-origin",
        }
      );

      if (!response.ok) {
        console.error("Failed to login as anonymous user", response);
        throw new Error("Failed to login as anonymous user");
      }
      // Redirect to the chat page and force a refresh
      window.location.href = "/chat";
    } catch (error) {
      console.error("Error logging in as anonymous user:", error);
      redirect("/auth/signup?error=Anonymous");
    }
  };

  useEffect(() => {
    loginAsAnonymousUser();
  }, []);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-background-100">
      <div className="bg-white p-8 rounded-lg shadow-md">
        <h1 className="text-2xl font-bold mb-4 text-center">
          Redirecting you to the chat page...
        </h1>
        <div className="flex justify-center">
          <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-background-800"></div>
        </div>
        <p className="mt-4 text-text-600 text-center">
          Please wait while we set up your anonymous session.
        </p>
      </div>
    </div>
  );
}
