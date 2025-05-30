import { NextRequest, NextResponse } from "next/server";

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  const { id } = params;
  
  if (!id) {
    return NextResponse.json(
      { error: "Repository ID is required" },
      { status: 400 }
    );
  }

  const authHeader = request.headers.get("authorization") || "";
  
  // Use direct IP address instead of localhost to avoid potential routing issues
  const defaultBackendBaseUrl = "http://127.0.0.1:8002"; // Use the port where your backend is running
  const backendBaseUrl = process.env.BACKEND_URL || defaultBackendBaseUrl;
  const cleanBackendBaseUrl = backendBaseUrl.endsWith("/")
    ? backendBaseUrl.slice(0, -1)
    : backendBaseUrl;
  
  const backendUrl = `${cleanBackendBaseUrl}/documentation/${id}`;

  console.log(
    `GET /api/documentation/${id}: Requesting documentation from backend at ${backendUrl}.`
  );

  try {
    const backendResponse = await fetch(backendUrl, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: authHeader,
      },
      cache: 'no-store',
      next: { revalidate: 0 },
    });

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text();
      console.error(`GET /api/documentation/${id}: Backend error:`, errorText);
      return NextResponse.json(
        { error: `Error fetching documentation: ${errorText}` },
        { status: backendResponse.status }
      );
    }

    const responseData = await backendResponse.json();
    return NextResponse.json(responseData);
  } catch (error) {
    console.error(`GET /api/documentation/${id}: Error:`, error);
    return NextResponse.json(
      { 
        error: `Failed to fetch documentation: ${error instanceof Error ? error.message : 'Unknown error'}`,
        documentation: null
      },
      { status: 500 }
    );
  }
}
