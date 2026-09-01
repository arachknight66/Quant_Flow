"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";

export function useRequireAuth() {
  const router = useRouter();
  const { isAuthenticated, accessToken } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated && !accessToken) {
      router.push("/login");
    }
  }, [isAuthenticated, accessToken, router]);

  return { isAuthenticated };
}
