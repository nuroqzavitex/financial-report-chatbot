import type { Metadata } from "next";
import { Be_Vietnam_Pro, Source_Serif_4 } from "next/font/google";
import "./globals.css";

// UI face drawn for Vietnamese diacritics; serif for reading answers
const ui = Be_Vietnam_Pro({
  variable: "--font-ui",
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600"],
});

const read = Source_Serif_4({
  variable: "--font-read",
  subsets: ["latin", "vietnamese"],
});

export const metadata: Metadata = {
  title: "Hỏi đáp BCTN Techcombank 2025",
  description:
    "Hỏi đáp báo cáo thường niên Techcombank 2025, có trích dẫn trang.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" className={`${ui.variable} ${read.variable}`}>
      <body className="antialiased">{children}</body>
    </html>
  );
}
