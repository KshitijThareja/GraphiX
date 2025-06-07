import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const repoUrl = searchParams.get('repo_url');

    if (!repoUrl) {
      return NextResponse.json(
        { error: "Missing required parameter: repo_url" },
        { status: 400 }
      );
    }

    // First check if there's an in-progress analysis
    const safeRepoId = encodeURIComponent(repoUrl.replace(/[^a-zA-Z0-9]/g, '_'));
    const pollInfoPath = `/tmp/graphix_processing_${safeRepoId}.json`;
    
    let processingInfo = null;
    try {
      const fileContent = await fs.readFile(pollInfoPath, 'utf-8');
      processingInfo = JSON.parse(fileContent);
      console.log(`Found processing info for ${repoUrl}:`, processingInfo);
    } catch (err) {
      // File doesn't exist, which is fine - no in-progress analysis
      console.log(`No processing info found for ${repoUrl}`);
    }

    // Now check if there are completed results from the backend
    const backendApiEndpoint = "/analysis/callgraph/status"; 
    const defaultBackendBaseUrl = "http://127.0.0.1:8000";
    const backendBaseUrl = process.env.BACKEND_URL || defaultBackendBaseUrl;
    const cleanBackendBaseUrl = backendBaseUrl.endsWith("/") ? backendBaseUrl.slice(0, -1) : backendBaseUrl;
    const backendUrl = `${cleanBackendBaseUrl}${backendApiEndpoint}?repo_url=${encodeURIComponent(repoUrl)}`;

    console.log(`GET /api/analysis/callgraph/status: Checking status for ${repoUrl} at ${backendUrl}`);
    
    try {
      // Get the authorization header from the request if present
      const authHeader = request.headers.get("authorization");
      
      const backendResponse = await fetch(backendUrl, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
          ...(authHeader ? { "Authorization": authHeader } : {})
        },
        cache: 'no-store',
        signal: AbortSignal.timeout(5000), // 5-second timeout for status check
      });

      if (backendResponse.ok) {
        const responseData = await backendResponse.json();
        console.log(`GET /api/analysis/callgraph/status: Received status from backend:`, 
          responseData.status || 'unknown status');
        
        // If analysis is complete, clean up the processing info file
        if (responseData.status === 'completed' && processingInfo) {
          try {
            await fs.unlink(pollInfoPath);
            console.log(`Removed processing info file for completed analysis: ${pollInfoPath}`);
          } catch (err) {
            console.warn(`Failed to remove processing info file: ${pollInfoPath}`, err);
          }
        }
        
        return NextResponse.json(responseData);
      } else {
        console.log(`Backend status check returned ${backendResponse.status}`);
        // If backend doesn't know about this analysis but we have processing info,
        // it means the analysis is still running but not completed yet
        if (processingInfo) {
          return NextResponse.json({
            status: 'processing',
            message: 'Analysis is still running on the backend',
            started_at: processingInfo.started_at,
            repo_url: repoUrl,
            framework_hint: processingInfo.framework_hint,
            research_grade: processingInfo.research_grade
          });
        }
        
        // Backend doesn't know about this analysis and we have no processing info
        return NextResponse.json({
          status: 'not_found',
          message: 'No analysis found for this repository',
        });
      }
    } catch (error) {
      console.error(`Error checking backend status:`, error);
      
      // If backend check fails but we have processing info, assume it's still processing
      if (processingInfo) {
        return NextResponse.json({
          status: 'processing',
          message: 'Analysis appears to be running but status check failed',
          started_at: processingInfo.started_at,
          repo_url: repoUrl
        });
      }
      
      // No processing info and backend check failed
      return NextResponse.json({
        status: 'unknown',
        message: 'Could not determine analysis status',
      });
    }
  } catch (error) {
    console.error(`Error in status check API route:`, error);
    return NextResponse.json(
      { 
        error: "Error checking analysis status",
        detail: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}
