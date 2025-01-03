"use client";
import { Button } from "@/components/ui/button";
import { redirect } from "next/navigation";
import { useEffect } from "react";

export default async function Page({ params }: { params: { id: string } }) {
  const tenantId = params.id;

  const loginAsAnonymousUser = async () => {
    try {
      const response = await fetch(
        `/api/tenants/anonymous-user?tenant_id=${encodeURIComponent(tenantId)}`,
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
      redirect("/chat?error=Failed to login as anonymous user");
    }
  };

  useEffect(() => {
    loginAsAnonymousUser();
  }, []);

  // TODO clarify
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
      <div className="bg-white p-8 rounded-lg shadow-md">
        <h1 className="text-2xl font-bold mb-4 text-center">
          Logging you in...
        </h1>
        <div className="flex justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
        </div>
        <p className="mt-4 text-gray-600 text-center">
          Please wait while we set up your anonymous session.
        </p>
      </div>
    </div>
  );
}
