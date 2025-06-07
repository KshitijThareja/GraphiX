"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
  
  }, [router]);
  return (
    <div className="flex items-center justify-center min-h-screen">


      {/* You could add a spinner component here for better UX */}
    </div>
  );
}
