import { NextResponse } from "next/server";

export async function GET() {
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/users`, {
      credentials: "include",
    });

    if (!response.ok) {
      return NextResponse.json({ hasUsers: false }, { status: 200 });
    }

    const users = await response.json();
    return NextResponse.json({ hasUsers: users.length > 0 }, { status: 200 });
  } catch (error) {
    console.error("Error checking users:", error);
    return NextResponse.json({ hasUsers: false }, { status: 200 });
  }
} 