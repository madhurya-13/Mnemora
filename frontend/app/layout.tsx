import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MNEMORA — An AI that remembers",
  description: "A personal AI assistant designed to remember, learn and evolve.",
  icons: { icon: "/mnemora-mark.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
