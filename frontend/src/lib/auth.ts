import { jwtDecode } from "jwt-decode";
export interface User {
  login: string;
  name: string;
  email: string;
  avatar_url: string;
}
export interface Token {
  access_token: string;
  token_type: string;
  user: User;
}
export const setToken = (token: string): void => {
  if (typeof window !== "undefined") {
    localStorage.setItem("token", token);
  }
};
export const getToken = (): string | null => {
  if (typeof window !== "undefined") {
    return localStorage.getItem("token");
  }
  return null;
};
export const removeToken = (): void => {
  if (typeof window !== "undefined") {
    localStorage.removeItem("token");
  }
};
export const getUser = (): User | null => {
  if (typeof window !== "undefined") {
    const token = getToken();
    if (!token) return null;
    try {
      const decoded: any = jwtDecode(token);
      return decoded.user || null;
    } catch (error) {
      return null;
    }
  }
  return null;
};
export const isAuthenticated = (): boolean => {
  if (typeof window !== "undefined") {
    const token = getToken();
    if (!token) return false;
    try {
      const decoded: any = jwtDecode(token);
      return decoded.exp * 1000 > Date.now();
    } catch (error) {
      return false;
    }
  }
  return false;
};
export const loginWithGitHub = async (): Promise<void> => {
  window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/auth/login`;
};
export const handleGitHubCallback = async (code: string): Promise<Token> => {
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/auth/callback?code=${code}`,
  );
  if (!response.ok) {
    throw new Error("Failed to authenticate with GitHub");
  }
  return response.json();
};
