"use client";

/**
 * Client-side provider wrapper – combines AuthProvider and any other
 * global providers (Toaster, etc.) so RootLayout can remain a server component.
 */

import React from "react";
import { Toaster } from "react-hot-toast";
import { AuthProvider } from "./auth";

export function AppProviders({ children }: { children: React.ReactNode }) {
    return (
        <AuthProvider>
            {children}
            <Toaster
                position="top-right"
                toastOptions={{
                    style: {
                        background: "#1e293b",
                        color: "#f1f5f9",
                        border: "1px solid #334155",
                    },
                }}
            />
        </AuthProvider>
    );
}