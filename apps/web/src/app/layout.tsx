import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "BLACK MAMBA", template: "%s · BLACK MAMBA" },
  description: "Evidence management for scam and fraud investigations.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full font-sans">{children}</body>
    </html>
  );
}
