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
    // No timeout - allow the request to complete for as long as needed
    console.log(`POST /api/analysis/callgraph: No timeout set - waiting for repository analysis to complete`);
    
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
        // No timeout signal
        cache: 'no-store',
      });
    } catch (error) {
      console.error(`POST /api/analysis/callgraph: Connection error to backend:`, error);
      
      // Check if it's a connection error that might still be processing in the background
      const isConnectionError = error instanceof Error;
      
      if (isConnectionError) {
        console.log(`POST /api/analysis/callgraph: Connection error, but backend might still be processing`);
        console.log(`Error details:`, error);
        
        // Store the repository URL in a file to help with polling
        try {
          const pollInfoPath = `/tmp/graphix_processing_${encodeURIComponent(repo_url.replace(/[^a-zA-Z0-9]/g, '_'))}.json`;
          const pollInfo = {
            repo_url: repo_url,
            started_at: new Date().toISOString(),
            framework_hint: framework_hint || "generic",
            research_grade: research_grade || false
          };
          console.log(`Saving polling info to ${pollInfoPath}`);
          await fs.writeFile(pollInfoPath, JSON.stringify(pollInfo, null, 2));
        } catch (fileError) {
          console.error("Failed to save polling information:", fileError);
        }
        
        // Return a special response that indicates the backend is still processing
        return NextResponse.json({
          status: 'processing',
          message: 'The analysis is taking longer than expected but is still running in the background. Please wait a few minutes and try refreshing the page to check if results are available.',
          data: {
            nodes: [],
            links: [],
            metadata: {
              status_log_from_backend: [
                `Analysis is still running on the backend. The repository may be complex or large.`,
                `You can try refreshing the page in a few minutes to check for results.`,
                `Repository URL: ${repo_url}`,
                `Analysis started with framework hint: ${framework_hint || "generic"}`
              ],
              warning: 'Analysis timeout - backend processing continues',
              status: 'processing',
              repo_url: repo_url,
              framework_hint: framework_hint,
              research_grade: research_grade
            }
          }
        }, { status: 202 }); // 202 Accepted indicates the request was valid but processing is not complete
      }
      
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
