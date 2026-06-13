"use client";

/**
 * AuthContext provider – manages JWT authentication state across the app.
 *
 * Stores tokens in localStorage and provides login/signup/logout actions
 * as well as the current user object to all child components.
 */

import React, {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
} from "react";
import api from "./api";

// ── Types ────────────────────────────────────────────────────

export interface AuthUser {
    id: number;
    email: string;
}

interface AuthState {
    user: AuthUser | null;
    isLoading: boolean;
    isAuthenticated: boolean;
    login: (email: string, password: string) => Promise<void>;
    signup: (email: string, password: string) => Promise<void>;
    logout: () => void;
}

// ── Helpers ──────────────────────────────────────────────────

const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
const AUTH_COOKIE_KEY = "auth_token";

function getStoredTokens(): { access: string | null; refresh: string | null } {
    if (typeof window === "undefined") return { access: null, refresh: null };
    return {
        access: localStorage.getItem(ACCESS_TOKEN_KEY),
        refresh: localStorage.getItem(REFRESH_TOKEN_KEY),
    };
}

function setStoredTokens(access: string, refresh: string): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, access);
    localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
    // Also set a cookie so Next.js middleware can read it for route protection
    document.cookie = `${AUTH_COOKIE_KEY}=${access}; path=/; max-age=86400; SameSite=Lax`;
}

function clearStoredTokens(): void {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    // Clear the auth cookie
    document.cookie = `${AUTH_COOKIE_KEY}=; path=/; max-age=0`;
}

function decodeJwtPayload(token: string): { user_id: number; email: string } | null {
    try {
        const base64 = token.split(".")[1];
        const json = atob(base64);
        return JSON.parse(json);
    } catch {
        return null;
    }
}

// ── Context ──────────────────────────────────────────────────

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    // On mount, try to restore session from stored tokens
    useEffect(() => {
        const { access } = getStoredTokens();
        if (access) {
            const payload = decodeJwtPayload(access);
            if (payload) {
                setUser({ id: payload.user_id, email: payload.email });
            } else {
                clearStoredTokens();
            }
        }
        setIsLoading(false);
    }, []);

    const login = useCallback(async (email: string, password: string) => {
        const res = await api.post("/auth/login", { email, password });
        const { access_token, refresh_token } = res.data;
        setStoredTokens(access_token, refresh_token);
        const payload = decodeJwtPayload(access_token);
        if (payload) {
            setUser({ id: payload.user_id, email: payload.email });
        }
    }, []);

    const signup = useCallback(async (email: string, password: string) => {
        const res = await api.post("/auth/signup", { email, password });
        const { access_token, refresh_token } = res.data;
        setStoredTokens(access_token, refresh_token);
        const payload = decodeJwtPayload(access_token);
        if (payload) {
            setUser({ id: payload.user_id, email: payload.email });
        }
    }, []);

    const logout = useCallback(() => {
        clearStoredTokens();
        setUser(null);
        if (typeof window !== "undefined") {
            window.location.href = "/login";
        }
    }, []);

    const value = useMemo<AuthState>(
        () => ({
            user,
            isLoading,
            isAuthenticated: user !== null,
            login,
            signup,
            logout,
        }),
        [user, isLoading, login, signup, logout],
    );

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
    const ctx = useContext(AuthContext);
    if (ctx === undefined) {
        throw new Error("useAuth must be used within an AuthProvider");
    }
    return ctx;
}

export default AuthContext;