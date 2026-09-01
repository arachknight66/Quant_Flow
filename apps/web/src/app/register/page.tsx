"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api-client";
import { useAuthStore } from "@/store/auth";
import { RiskSelector, RiskTolerance } from "@/components/ui/RiskSelector";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [riskTolerance, setRiskTolerance] = useState<RiskTolerance>("moderate");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Client-side validation
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);

    try {
      await api.auth.register(email, password, riskTolerance);
      // Automatically login after registration
      const tokenRes = await api.auth.login(email, password);
      const user = await api.auth.me();
      useAuthStore.getState().setToken(tokenRes.access_token, user);
      router.push("/");
    } catch (err: any) {
      setError(err?.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="flex items-center justify-center min-h-screen"
      style={{ background: "var(--bg)" }}
    >
      <div className="card w-full max-w-sm p-8">
        {/* Branding */}
        <div className="flex items-center gap-2 mb-8 justify-center">
          <div
            style={{
              width: 28,
              height: 28,
              background: "var(--accent)",
              borderRadius: 6,
              flexShrink: 0,
            }}
          />
          <span
            className="font-semibold text-sm tracking-wide"
            style={{ color: "var(--text)" }}
          >
            QuantPlatform
          </span>
        </div>

        <h1
          className="text-lg font-bold mb-6 text-center"
          style={{ color: "var(--text)" }}
        >
          Create your account
        </h1>

        {error && (
          <div
            className="text-xs mb-4 p-3 rounded-lg text-center"
            style={{
              color: "var(--red)",
              background: "rgba(255,68,102,0.08)",
              border: "1px solid rgba(255,68,102,0.2)",
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label
              className="text-xs font-medium"
              style={{ color: "var(--text-dim)" }}
            >
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg outline-none"
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
              placeholder="you@example.com"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              className="text-xs font-medium"
              style={{ color: "var(--text-dim)" }}
            >
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg outline-none"
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
              placeholder="Min. 8 characters"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              className="text-xs font-medium"
              style={{ color: "var(--text-dim)" }}
            >
              Confirm Password
            </label>
            <input
              type="password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg outline-none"
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
              placeholder="••••••••"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              className="text-xs font-medium"
              style={{ color: "var(--text-dim)" }}
            >
              Risk Tolerance
            </label>
            <RiskSelector value={riskTolerance} onChange={setRiskTolerance} />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 text-sm font-semibold rounded-lg transition-opacity"
            style={{
              background: "var(--accent)",
              color: "#000",
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? "Creating account…" : "Sign up"}
          </button>
        </form>

        <p
          className="text-xs text-center mt-6"
          style={{ color: "var(--text-dim)" }}
        >
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-medium hover:underline"
            style={{ color: "var(--accent)" }}
          >
            Log in
          </Link>
        </p>
      </div>
    </div>
  );
}
