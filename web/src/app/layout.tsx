import "./globals.css";

import { Inter } from "next/font/google";


declare global {
  interface Window {
    justLoggedIn: any;
  }
}

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata = {
  title: "Danswer",
  description: "Question answering for your documents",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        className={`${inter.variable} font-sans text-default bg-background`}
      >
        {children}
      </body>
    </html>
  );
}
