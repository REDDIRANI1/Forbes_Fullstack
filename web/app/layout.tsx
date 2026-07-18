import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = { title: "Rate Tracker", description: "Compare current interest rates" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
