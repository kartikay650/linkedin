import { useEffect, useState } from "react";
import { supabase } from "./supabase";

export default function AuthGate({ children }) {
  const [session, setSession] = useState(undefined); // undefined = still loading

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (session === undefined) {
    return <div style={{ padding: 40, color: "var(--text-muted)", fontFamily: "inherit" }}>Loading…</div>;
  }
  if (!session) return <Login />;

  return (
    <>
      {children}
      <button
        onClick={() => supabase.auth.signOut()}
        title="Sign out"
        style={{
          position: "fixed", bottom: 14, left: 14, zIndex: 50,
          padding: "6px 12px", borderRadius: 8, border: "1px solid var(--border)",
          background: "var(--surface)", color: "var(--text-muted)", fontSize: 12, fontWeight: 600, cursor: "pointer",
        }}
      >
        Sign out
      </button>
    </>
  );
}

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
    if (error) setError(error.message);
    setBusy(false);
  };

  const inputStyle = {
    width: "100%", padding: "10px 12px", borderRadius: 8, border: "1px solid var(--border)",
    fontSize: 14, fontFamily: "inherit", marginBottom: 10, boxSizing: "border-box",
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)" }}>
      <form
        onSubmit={submit}
        style={{
          width: 320, background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 12, padding: 28, boxShadow: "var(--shadow)", fontFamily: "inherit",
        }}
      >
        <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Engagement Dashboard</div>
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 18 }}>Sign in to continue</div>
        <input style={inputStyle} type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
        <input style={inputStyle} type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        {error && <div style={{ fontSize: 12, color: "var(--danger)", marginBottom: 10 }}>{error}</div>}
        <button
          type="submit"
          disabled={busy || !email || !password}
          style={{
            width: "100%", padding: "10px", borderRadius: 8, border: "none",
            background: "var(--primary)", color: "#fff", fontSize: 14, fontWeight: 600,
            cursor: busy ? "default" : "pointer", opacity: busy ? 0.7 : 1,
          }}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
