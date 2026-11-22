import React, { useState } from "react";

const USERS_KEY = "travelintel-demo-users-v1";
const SESSION_KEY = "travelintel-auth-session-v1";
const PASSWORD_ITERATIONS = 120_000;

function readUsers() {
  const saved = window.localStorage.getItem(USERS_KEY);
  if (!saved) return [];
  const users = JSON.parse(saved);
  if (!Array.isArray(users)) throw new Error("Saved account data is invalid.");
  return users;
}

function readSession() {
  try {
    const saved = window.localStorage.getItem(SESSION_KEY) || window.sessionStorage.getItem(SESSION_KEY);
    if (!saved) return { user: null, error: "" };
    const session = JSON.parse(saved);
    if (typeof session.email !== "string" || typeof session.name !== "string") {
      return { user: null, error: "Your saved sign-in is invalid. Please log in again." };
    }
    return { user: { email: session.email, name: session.name }, error: "" };
  } catch {
    return { user: null, error: "Saved sign-in data could not be read. Please log in again." };
  }
}

function toHex(bytes) {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function fromHex(value) {
  return Uint8Array.from(value.match(/.{2}/g) || [], (byte) => Number.parseInt(byte, 16));
}

async function hashPassword(password, salt) {
  const key = await window.crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await window.crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: fromHex(salt), iterations: PASSWORD_ITERATIONS },
    key,
    256,
  );
  return toHex(bits);
}

function newSalt() {
  return toHex(window.crypto.getRandomValues(new Uint8Array(16)));
}

function validEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function PasswordField({ id, label, value, onChange, autoComplete, show, onToggle, required = true }) {
  return (
    <label className="auth-field" htmlFor={id}>
      <span>{label}</span>
      <span className="auth-password-wrap">
        <input
          id={id}
          type={show ? "text" : "password"}
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          required={required}
          minLength={8}
        />
        <button type="button" className="auth-password-toggle" onClick={onToggle} aria-label={show ? "Hide password" : "Show password"}>
          {show ? "Hide" : "Show"}
        </button>
      </span>
    </label>
  );
}

function AuthPage({ mode, onModeChange, error, message, onSubmit, remember, setRemember }) {
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const isRegister = mode === "register";
  const isForgot = mode === "forgot";
  const title = isRegister ? "Create your account" : isForgot ? "Reset your password" : "Customer Login";

  const submit = (event) => {
    event.preventDefault();
    onSubmit({ fullName, email, password, confirmPassword });
  };

  return (
    <main className="auth-page">
      <section className="auth-showcase">
        <div className="auth-brand">
          <span className="auth-brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span>Travel<span>Intel</span></span>
        </div>
        <div className="auth-story">
          <p className="auth-eyebrow">YOUR NEXT JOURNEY STARTS HERE</p>
          <h1>Travel with<br />a little more <em>insight.</em></h1>
          <p>Discover destinations, match your mood and plan a journey shaped around you.</p>
          <div className="auth-trip-tag"><span>✦</span> Thoughtful travel, powered by real data.</div>
        </div>
        <span className="auth-image-note">A world of possibility awaits</span>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-mobile-brand"><span className="auth-brand-mark" aria-hidden="true"><i /><i /><i /></span>Travel<span>Intel</span></div>
          <p className="auth-eyebrow">TRAVELINTEL · MEMBER ACCESS</p>
          <h2>{title}</h2>
          <p className="auth-intro">
            {isRegister ? "Join us and start planning your next great escape." : isForgot ? "Set a new password for your local demo account." : "Sign in to continue to your TravelIntel experience."}
          </p>
          {error && <p className="auth-message error" role="alert">{error}</p>}
          {message && <p className="auth-message success" role="status">{message}</p>}
          <form noValidate onSubmit={submit}>
            {isRegister && (
              <label className="auth-field" htmlFor="auth-name">
                <span>Full name</span>
                <input id="auth-name" value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="name" required />
              </label>
            )}
            <label className="auth-field" htmlFor="auth-email">
              <span>Email address</span>
              <input
                id="auth-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                required
              />
            </label>
            <PasswordField
              id="auth-password"
              label={isForgot ? "New password" : "Password"}
              value={password}
              onChange={setPassword}
              autoComplete={isRegister || isForgot ? "new-password" : "current-password"}
              show={showPassword}
              onToggle={() => setShowPassword((value) => !value)}
            />
            {(isRegister || isForgot) && (
              <PasswordField
                id="auth-confirm-password"
                label="Confirm password"
                value={confirmPassword}
                onChange={setConfirmPassword}
                autoComplete="new-password"
                show={showConfirm}
                onToggle={() => setShowConfirm((value) => !value)}
              />
            )}
            {mode === "login" && (
              <div className="auth-options">
                <label><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> Remember me</label>
                <button type="button" onClick={() => onModeChange("forgot")}>Forgot password?</button>
              </div>
            )}
            <button type="submit" className="auth-submit">
              {isRegister ? "Create account" : isForgot ? "Set new password" : "Log in"}
              <span aria-hidden="true">→</span>
            </button>
          </form>
          {mode === "login" && <p className="auth-switch">Don't have an account? <button onClick={() => onModeChange("register")}>Register</button></p>}
          {mode !== "login" && <p className="auth-switch">Already have an account? <button onClick={() => onModeChange("login")}>Return to login</button></p>}
          <p className="auth-demo-note">Local college demonstration only. No email is sent, and these accounts are not production-secure.</p>
        </div>
      </section>
    </main>
  );
}

function AdminLoginPage({ error, onSubmit }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const submit = (event) => {
    event.preventDefault();
    onSubmit({ email, password });
  };

  return (
    <main className="admin-auth-page">
      <section className="admin-auth-aside">
        <div className="admin-auth-brand">
          <span className="auth-brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span>Travel<span>Intel</span></span>
        </div>
        <div className="admin-auth-story">
          <p className="admin-auth-eyebrow">TRAVELINTEL · OPERATIONS</p>
          <h1>Insight for<br />every journey.</h1>
          <p>Manage travel analytics and operational insights from one secure workspace.</p>
        </div>
        <p className="admin-auth-aside-note">AUTHORIZED ADMINISTRATORS ONLY</p>
      </section>
      <section className="admin-auth-panel">
        <div className="admin-auth-card">
          <div className="admin-auth-mobile-brand">
            <span className="auth-brand-mark" aria-hidden="true"><i /><i /><i /></span>
            <span>Travel<span>Intel</span></span>
          </div>
          <p className="admin-auth-eyebrow">ADMINISTRATOR PORTAL</p>
          <h2>Admin Login</h2>
          <p className="admin-auth-intro">Sign in with your administrator credentials to continue.</p>
          {error && <p className="auth-message error" role="alert">{error}</p>}
          <form noValidate onSubmit={submit}>
            <label className="admin-auth-field" htmlFor="admin-email">
              <span>Admin email</span>
              <input
                id="admin-email"
                name="admin-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="admin-auth-field" htmlFor="admin-password">
              <span>Admin password</span>
              <span className="admin-auth-password-wrap">
                <input
                  id="admin-password"
                  name="admin-password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </span>
            </label>
            <button type="submit" className="admin-auth-submit">
              Sign in to admin
              <span aria-hidden="true">→</span>
            </button>
          </form>
          <p className="admin-auth-caption">Credentials are verified by the TravelIntel API.</p>
          <a className="admin-auth-customer-link" href="/customer">Customer login</a>
        </div>
      </section>
    </main>
  );
}

export default function AuthGate({ children, portal = "customer" }) {
  const [initial] = useState(() => portal === "admin" ? { user: null, error: "" } : readSession());
  const [user, setUser] = useState(initial.user);
  const [error, setError] = useState(initial.error);
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState("login");
  const [remember, setRemember] = useState(false);

  const changeMode = (nextMode) => {
    setMode(nextMode);
    setError("");
    setMessage(nextMode === "forgot" ? "Demonstration reset: no email will be sent. Enter your registered email and choose a new password." : "");
  };

  const persistSession = (account, rememberMe) => {
    const storage = rememberMe ? window.localStorage : window.sessionStorage;
    const otherStorage = rememberMe ? window.sessionStorage : window.localStorage;
    otherStorage.removeItem(SESSION_KEY);
    storage.setItem(SESSION_KEY, JSON.stringify({ email: account.email, name: account.name }));
    setUser({ email: account.email, name: account.name });
    setError("");
  };

  const onSubmit = async ({ fullName, email, password, confirmPassword }) => {
    setError("");
    setMessage("");
    const normalizedEmail = email.trim().toLowerCase();
    try {
      if (!normalizedEmail || (!validEmail(normalizedEmail))) {
        setError("Enter a valid email address.");
        return;
      }

      if (portal === "admin") {
        if (!password) {
          setError("Enter your admin password.");
          return;
        }
        const response = await fetch("/api/admin/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: normalizedEmail, password }),
        });
        let payload;
        try {
          payload = await response.json();
        } catch {
          throw new Error(`The TravelIntel API returned an invalid response (${response.status}).`);
        }
        if (!response.ok) {
          setError(payload.error || "Admin email or password is incorrect.");
          return;
        }
        if (payload.role !== "admin" || typeof payload.email !== "string") {
          setError("Admin authentication could not be verified.");
          return;
        }
        setUser({ email: payload.email, name: "Administrator" });
        return;
      }

      const users = readUsers();
      if (mode === "register") {
        const name = fullName.trim();
        if (!name || !password || !confirmPassword) {
          setError("Complete all required fields.");
          return;
        }
        if (password.length < 8) {
          setError("Use a password with at least 8 characters.");
          return;
        }
        if (password !== confirmPassword) {
          setError("Passwords do not match.");
          return;
        }
        if (users.some((account) => account.email === normalizedEmail)) {
          setError("An account with this email already exists. Please log in.");
          return;
        }
        const salt = newSalt();
        const passwordHash = await hashPassword(password, salt);
        users.push({ name, email: normalizedEmail, salt, passwordHash });
        window.localStorage.setItem(USERS_KEY, JSON.stringify(users));
        setMode("login");
        setMessage("Account created. You can now log in.");
        return;
      }

      if (mode === "forgot") {
        if (!password || !confirmPassword) {
          setError("Enter and confirm your new password.");
          return;
        }
        if (password.length < 8) {
          setError("Use a password with at least 8 characters.");
          return;
        }
        if (password !== confirmPassword) {
          setError("Passwords do not match.");
          return;
        }
        const account = users.find((item) => item.email === normalizedEmail);
        if (!account) {
          setError("No local account was found for this email.");
          return;
        }
        account.salt = newSalt();
        account.passwordHash = await hashPassword(password, account.salt);
        window.localStorage.setItem(USERS_KEY, JSON.stringify(users));
        setMode("login");
        setMessage("Demo password reset complete. No email was sent. Log in using your new password.");
        return;
      }

      if (!password) {
        setError("Enter your password.");
        return;
      }
      const account = users.find((item) => item.email === normalizedEmail);
      if (!account || !account.salt || !account.passwordHash || await hashPassword(password, account.salt) !== account.passwordHash) {
        setError("Email or password is incorrect.");
        return;
      }
      persistSession(account, remember);
    } catch (cause) {
      setError(cause instanceof Error ? `Authentication could not be completed: ${cause.message}` : "Authentication could not be completed.");
    }
  };

  const logout = () => {
    try {
      if (portal === "customer") {
        window.localStorage.removeItem(SESSION_KEY);
        window.sessionStorage.removeItem(SESSION_KEY);
      }
      setUser(null);
      setMode("login");
      setError("");
      setMessage("");
    } catch (cause) {
      setError(cause instanceof Error ? `Could not end the saved session: ${cause.message}` : "Could not end the saved session.");
    }
  };

  if (!user) {
    if (portal === "admin") {
      return <AdminLoginPage onSubmit={onSubmit} error={error} />;
    }
    return (
      <AuthPage
        key={mode}
        mode={mode}
        onModeChange={changeMode}
        onSubmit={onSubmit}
        error={error}
        message={message}
        remember={remember}
        setRemember={setRemember}
      />
    );
  }
  return children(user, logout);
}
