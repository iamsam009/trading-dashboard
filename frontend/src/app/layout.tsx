import type { Metadata } from "next";
import "./globals.css";
import { AppProviders } from "@/lib/providers";

export const metadata: Metadata = {
    title: "Trading Dashboard",
    description: "Real-time trading dashboard with strategy backtesting and risk management",
    icons: {
        icon: "/favicon.ico",
    },
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="en">
            <body className="min-h-screen bg-slate-950 text-white antialiased">
                <AppProviders>{children}</AppProviders>
            </body>
        </html>
    );
}