import type { Metadata } from "next";
import "./globals.css";

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
                {children}
            </body>
        </html>
    );
}