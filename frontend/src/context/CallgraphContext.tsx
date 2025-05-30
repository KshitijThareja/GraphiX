"use client";
import {
  createContext,
  useContext,
  useState,
  ReactNode,
  useEffect,
} from "react";
interface CallgraphContextType {
  repoUrl: string;
  setRepoUrl: (url: string) => void;
  callgraphData: any;
  setCallgraphData: (data: any) => void;
  metrics: any;
  setMetrics: (metrics: any) => void;
  clearCallgraphData: () => void;
}
const CallgraphContext = createContext<CallgraphContextType | undefined>(
  undefined,
);
export function CallgraphProvider({ children }: { children: ReactNode }) {
  const [repoUrl, setRepoUrl] = useState<string>(() => {
    if (typeof window !== "undefined") {
      const savedRepoUrl = localStorage.getItem("repoUrl");
      return savedRepoUrl || "";
    }
    return "";
  });
  const [callgraphData, setCallgraphData] = useState<any>(() => {
    if (typeof window !== "undefined") {
      const savedCallgraphData = localStorage.getItem("callgraphData");
      return savedCallgraphData ? JSON.parse(savedCallgraphData) : null;
    }
    return null;
  });
  const [metrics, setMetrics] = useState<any>(() => {
    if (typeof window !== "undefined") {
      const savedMetrics = localStorage.getItem("metrics");
      return savedMetrics ? JSON.parse(savedMetrics) : null;
    }
    return null;
  });
  useEffect(() => {
    console.log("CallgraphContext updated:", {
      repoUrl,
      callgraphData,
      metrics,
    });
    if (repoUrl) {
      localStorage.setItem("repoUrl", repoUrl);
    } else {
      localStorage.removeItem("repoUrl");
    }
    if (callgraphData) {
      localStorage.setItem("callgraphData", JSON.stringify(callgraphData));
    } else {
      localStorage.removeItem("callgraphData");
    }
    if (metrics) {
      localStorage.setItem("metrics", JSON.stringify(metrics));
    } else {
      localStorage.removeItem("metrics");
    }
  }, [repoUrl, callgraphData, metrics]);
  const clearCallgraphData = () => {
    setRepoUrl("");
    setCallgraphData(null);
    setMetrics(null);
    localStorage.removeItem("repoUrl");
    localStorage.removeItem("callgraphData");
    localStorage.removeItem("metrics");
  };
  return (
    <CallgraphContext.Provider
      value={{
        repoUrl,
        setRepoUrl,
        callgraphData,
        setCallgraphData,
        metrics,
        setMetrics,
        clearCallgraphData,
      }}
    >
      {children}
    </CallgraphContext.Provider>
  );
}
export function useCallgraph() {
  const context = useContext(CallgraphContext);
  if (!context) {
    throw new Error("useCallgraph must be used within a CallgraphProvider");
  }
  return context;
}
