import { NextRequest, NextResponse } from 'next/server';
export const dynamic = 'force-dynamic'; 
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const repoUrl = searchParams.get('repo_url');
  const researchGrade = searchParams.get('research_grade') === 'true';
  const frameworkHint = searchParams.get('framework_hint') || 'generic';
  const contextSensitivity = searchParams.get('context_sensitivity') || '2';
  if (!repoUrl) {
    return new NextResponse(
      JSON.stringify({ error: 'Missing required parameter: repo_url' }),
      { status: 400, headers: { 'Content-Type': 'application/json' } }
    );
  }
  try {
    const backendUrl = new URL(`${process.env.BACKEND_URL || 'http:
    backendUrl.search = new URLSearchParams({
      repo_url: repoUrl,
      research_grade: researchGrade.toString(),
      framework_hint: frameworkHint,
      context_sensitivity: contextSensitivity
    }).toString();
    const backendResponse = await fetch(backendUrl.toString(), {
      headers: {
        'Accept': 'text/event-stream',
      },
    });
    if (!backendResponse.ok) {
      throw new Error(`Backend request failed with status ${backendResponse.status}`);
    }
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    (async () => {
      try {
        const reader = backendResponse.body?.getReader();
        if (!reader) throw new Error('No response body');
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          await writer.write(value);
        }
      } catch (error) {
        console.error('Error reading from backend:', error);
      } finally {
        await writer.close();
      }
    })();
    return new NextResponse(readable, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });
  } catch (error) {
    console.error('Error in API route:', error);
    return new NextResponse(
      JSON.stringify({ error: 'Failed to connect to analysis service' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
}
