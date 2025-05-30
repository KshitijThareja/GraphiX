import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";
export const dynamic = "force-dynamic";
export async function POST(request: NextRequest) {
  let repo_url_from_body = "";
  try {
    const requestBody = await request.json();
    const { repo_url, research_grade, framework_hint, context_sensitivity } =
      requestBody;
    repo_url_from_body = repo_url;
    const authHeader = request.headers.get("authorization");
    if (!repo_url) {
      console.error(
        "POST /api/analysis/callgraph: Missing required parameter: repo_url",
      );
      return NextResponse.json(
        { error: "Missing required parameter: repo_url" },
        { status: 400 },
      );
    }
    if (!authHeader) {
      console.error(
        "POST /api/analysis/callgraph: Missing authorization header for repo:",
        repo_url,
      );
      return NextResponse.json(
        { error: "Missing authorization header" },
        { status: 401 },
      );
    }
    const backendApiEndpoint = "/analysis/callgraph"; 
    // Use direct IP address instead of localhost to avoid potential routing issues
    const defaultBackendBaseUrl = "http://127.0.0.1:8000"; // Default backend base URL

    
    const backendBaseUrl = process.env.BACKEND_URL || defaultBackendBaseUrl;

    
    const cleanBackendBaseUrl = backendBaseUrl.endsWith("/")
      ? backendBaseUrl.slice(0, -1)
      : backendBaseUrl;
    const backendUrl = `${cleanBackendBaseUrl}${backendApiEndpoint}`;

    console.log(
      `POST /api/analysis/callgraph: Forwarding request for ${repo_url} to backend at ${backendUrl}.`,
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
          repo_url,
          research_grade: research_grade || false,
          framework_hint: framework_hint || "generic",
          context_sensitivity: context_sensitivity || 2,
        }),
        // Increased timeout for large repositories
        signal: AbortSignal.timeout(300000), // 5 minutes timeout
        // Add additional options for better reliability
        cache: 'no-store',
        next: { revalidate: 0 },
      });
    } catch (error) {
      console.error(`POST /api/analysis/callgraph: Connection error to backend:`, error);
      return NextResponse.json({
        error: `Cannot connect to backend server at ${backendUrl}. Please ensure the backend server is running.`,
        detail: error instanceof Error ? error.message : 'Unknown connection error',
        status: 'connection_error',
        data: {
          nodes: [],
          links: [],
          metadata: {
            error: `Backend connection failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
            status: 'error',
          }
        }
      }, { status: 503 });
    }
    const responseData = await backendResponse.json();
    if (!backendResponse.ok) {
      console.error(
        `POST /api/analysis/callgraph: Backend request for ${repo_url} failed with status ${backendResponse.status}. Response:`,
        responseData,
      );
      try {
        const filePath = "/tmp/backend_callgraph_response.json";
        await fs.writeFile(filePath, JSON.stringify(responseData, null, 2));
        console.log(`Backend response saved to ${filePath}`);
      } catch (fileError) {
        console.error("Failed to save backend response:", fileError);
      }
      return NextResponse.json(responseData, {
        status: backendResponse.status,
      });
    }
    console.log(
      `POST /api/analysis/callgraph: Received JSON response from backend for ${repo_url}.`,
    );
    try {
      const filePath = "/tmp/backend_callgraph_response.json";
      await fs.writeFile(filePath, JSON.stringify(responseData, null, 2));
      console.log(`Backend response saved to ${filePath}`);
    } catch (fileError) {
      console.error("Failed to save backend response:", fileError);
    }
    return NextResponse.json(responseData);
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "An unknown error occurred";
    console.error(
      `POST /api/analysis/callgraph: Error in Next.js API route for repo "${repo_url_from_body || "unknown"}":`,
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
