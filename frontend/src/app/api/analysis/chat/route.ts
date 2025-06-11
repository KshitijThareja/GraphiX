import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  let repo_url_from_body = "";
  
  try {
    const requestBody = await request.json();
    const { query, repo_url, callgraph_data, documentation_data } = requestBody;
    repo_url_from_body = repo_url;
    
    const authHeader = request.headers.get("authorization");
    
    if (!query || !repo_url) {
      console.error(
        "POST /api/analysis/chat: Missing required parameters: query or repo_url",
      );
      return NextResponse.json(
        { error: "Missing required parameters: query or repo_url" },
        { status: 400 },
      );
    }
    
    if (!authHeader) {
      console.error(
        "POST /api/analysis/chat: Missing authorization header for repo:",
        repo_url,
      );
      return NextResponse.json(
        { error: "Missing authorization header" },
        { status: 401 },
      );
    }
    
    const backendApiEndpoint = "/analysis/chat";
    const defaultBackendBaseUrl = "http://127.0.0.1:8000"; // Default backend base URL
    const backendBaseUrl = process.env.BACKEND_URL || defaultBackendBaseUrl;
    const cleanBackendBaseUrl = backendBaseUrl.endsWith("/")
      ? backendBaseUrl.slice(0, -1)
      : backendBaseUrl;
    const backendUrl = `${cleanBackendBaseUrl}${backendApiEndpoint}`;

    console.log(
      `POST /api/analysis/chat: Forwarding request for ${repo_url} to backend at ${backendUrl}.`,
    );
    
    let backendResponse;
    try {
      backendResponse = await fetch(backendUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: authHeader,
        },
        body: JSON.stringify({
          query,
          repo_url,
          callgraph_data,
          documentation_data,
        }),
        cache: 'no-store',
      });
    } catch (error) {
      console.error(`POST /api/analysis/chat: Connection error to backend:`, error);
      
      return NextResponse.json({
        error: `Cannot connect to backend server at ${backendUrl}. Please ensure the backend server is running.`,
        detail: error instanceof Error ? error.message : 'Unknown connection error',
        status: 'connection_error',
      }, { status: 503 });
    }
    
    const responseData = await backendResponse.json();
    
    if (!backendResponse.ok) {
      console.error(
        `POST /api/analysis/chat: Backend request for ${repo_url} failed with status ${backendResponse.status}. Response:`,
        responseData,
      );
      return NextResponse.json(responseData, {
        status: backendResponse.status,
      });
    }
    
    console.log(
      `POST /api/analysis/chat: Received JSON response from backend for ${repo_url}.`,
    );
    
    return NextResponse.json(responseData);
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "An unknown error occurred";
    console.error(
      `POST /api/analysis/chat: Error in Next.js API route for repo "${repo_url_from_body || "unknown"}":`,
      errorMessage,
      error,
    );
    return NextResponse.json(
      {
        error: `Frontend API route error: ${errorMessage}`,
        detail: error instanceof Error ? error.stack : undefined,
      },
      { status: 500 },
    );
  }
} 