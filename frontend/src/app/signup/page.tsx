"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";

export default function SignupPage() {
    const router = useRouter();
    const { signup, isAuthenticated } = useAuth();

    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState("");
    const [submitting, setSubmitting] = useState(false);

    // If already logged in, redirect to dashboard
    React.useEffect(() => {
        if (isAuthenticated) {
            router.replace("/dashboard");
        }
    }, [isAuthenticated, router]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!email.trim() || !password) {
            setError("Please enter both email and password.");
            return;
        }
        if (password !== confirmPassword) {
            setError("Passwords do not match.");
            return;
        }
        if (password.length < 8) {
            setError("Password must be at least 8 characters.");
            return;
        }
        setError("");
        setSubmitting(true);
        try {
            await signup(email.trim(), password);
            router.replace("/dashboard");
        } catch (err: unknown) {
            const detail = (err as { response?: { data?: { detail?: string } } })
                ?.response?.data?.detail;
            setError(
                typeof detail === "string" ? detail : "Signup failed. Please try again.",
            );
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
            <div className="w-full max-w-sm">
                {/* Logo / Brand */}
                <div className="text-center mb-8">
                    <h1 className="text-2xl font-bold text-white tracking-tight">
                        Trading Dashboard
                    </h1>
                    <p className="text-slate-400 mt-1 text-sm">
                        Create a new account
                    </p>
                </div>

                {/* Form Card */}
                <form
                    onSubmit={handleSubmit}
                    className="bg-slate-900 border border-slate-700 rounded-lg p-6 space-y-4"
                >
                    {error && (
                        <div className="bg-red-900/30 border border-red-700 text-red-400 text-sm rounded px-3 py-2">
                            {error}
                        </div>
                    )}

                    <div>
                        <label
                            htmlFor="email"
                            className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider"
                        >
                            Email
                        </label>
                        <input
                            id="email"
                            type="email"
                            autoComplete="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                            placeholder="you@example.com"
                        />
                    </div>

                    <div>
                        <label
                            htmlFor="password"
                            className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider"
                        >
                            Password
                        </label>
                        <input
                            id="password"
                            type="password"
                            autoComplete="new-password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                            minLength={8}
                            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                            placeholder="Min. 8 characters"
                        />
                    </div>

                    <div>
                        <label
                            htmlFor="confirmPassword"
                            className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider"
                        >
                            Confirm Password
                        </label>
                        <input
                            id="confirmPassword"
                            type="password"
                            autoComplete="new-password"
                            value={confirmPassword}
                            onChange={(e) => setConfirmPassword(e.target.value)}
                            required
                            minLength={8}
                            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                            placeholder="Re-enter password"
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={submitting}
                        className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 disabled:cursor-not-allowed text-white font-medium rounded px-4 py-2.5 text-sm transition-colors"
                    >
                        {submitting ? "Creating account…" : "Create account"}
                    </button>
                </form>

                {/* Footer */}
                <p className="text-center text-slate-500 text-sm mt-6">
                    Already have an account?{" "}
                    <Link
                        href="/login"
                        className="text-blue-400 hover:text-blue-300 underline"
                    >
                        Sign in
                    </Link>
                </p>
            </div>
        </div>
    );
}