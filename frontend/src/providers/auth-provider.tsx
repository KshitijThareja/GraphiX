"use client";
import {
  createContext,
  useContext,
  ReactNode,
  useState,
  useEffect,
} from "react";
import {
  getToken,
  getUser,
  isAuthenticated,
  removeToken,
  setToken,
  User,
} from "@/lib/auth";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  login: () => Promise<void>;
  logout: () => void;
  loading: boolean;
}
const AuthContext = createContext<AuthContextType | undefined>(undefined);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isAuth, setIsAuth] = useState(false);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  useEffect(() => {
    async function loadUser() {
      const token = getToken();
      if (token) {
        const userData = getUser();
        setUser(userData);
        setIsAuth(true);
      } else {
        setIsAuth(false);
      }
      setLoading(false);
    }
    loadUser();
  }, []);
  useEffect(() => {
    async function handleCallback() {
      if (!searchParams) return;
      const code = searchParams.get("code");
      if (pathname === "/auth/callback" && code) {
        try {
          console.log("Exchanging code for token...");
          const response = await fetch(
            `/api/backend/auth/callback?code=${code}`,
            {
              method: "GET",
              headers: {
                "Content-Type": "application/json",
              },
            },
          );
          if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(
              `Failed to exchange code for token: ${response.status} - ${JSON.stringify(errorData)}`,
            );
          }
          const data = await response.json();
          const { access_token, user } = data;
          setToken(access_token);
          localStorage.setItem("user", JSON.stringify(user));
          setUser(user);
          setIsAuth(true);
          const returnUrl = localStorage.getItem("returnUrl") || "/";
          localStorage.removeItem("returnUrl");
          router.push(returnUrl);
        } catch (error) {
          console.error("Callback handling failed:", error);
          router.push("/?error=auth_failed");
        }
      }
    }
    handleCallback();
  }, [pathname, searchParams, router]);
  const login = async () => {
    try {
      localStorage.setItem(
        "returnUrl",
        window.location.pathname + window.location.search,
      );
      const githubOAuthUrl = `https://github.com/login/oauth/authorize?client_id=${process.env.NEXT_PUBLIC_GITHUB_CLIENT_ID}&redirect_uri=${encodeURIComponent(window.location.origin + "/auth/callback")}`; // TODO: Add scope and state parameters
      if (!githubOAuthUrl) {
        throw new Error("Failed to construct GitHub OAuth URL");
      }
      window.location.href = githubOAuthUrl;
    } catch (error) {
      console.error("Login failed:", error);
      router.push("/?error=login_failed");
    }
  };
  const logout = () => {
    removeToken();
    localStorage.removeItem("user");
    setUser(null);
    setIsAuth(false);
    router.push("/");
  };
  const value = {
    user,
    isAuthenticated: isAuth,
    login,
    logout,
    loading,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
