import { NextApiRequest, NextApiResponse } from "next";
import { getToken } from "next-auth/jwt";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse,
) {
  // This is a catch-all route that will handle all auth-related API routes
  // Forward the request to the backend
  const backendUrl = `http://localhost:8000/auth${req.url?.replace("/api/auth", "")}`;

  try {
    const response = await fetch(backendUrl, {
      method: req.method,
      headers: {
        ...req.headers,
        "Content-Type": "application/json",
      },
      body:
        req.method !== "GET" && req.method !== "HEAD"
          ? JSON.stringify(req.body)
          : undefined,
    });

    const data = await response.json();

    // Forward the response from the backend
    res.status(response.status).json(data);
  } catch (error) {
    console.error("Auth API error:", error);
    res.status(500).json({ error: "Internal server error" });
  }
}
