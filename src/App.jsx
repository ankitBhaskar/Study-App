import React, { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  Clock,
  FileText,
  Headphones,
  History,
  Layers,
  ListChecks,
  LogOut,
  MessageCircle,
  Minus,
  Pause,
  Play,
  MessageSquarePlus,
  RotateCcw,
  Send,
  Sparkles,
  Star,
  TrendingDown,
  TrendingUp,
  Upload,
  X,
} from "lucide-react";
import {
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
} from "firebase/auth";
import ReactMarkdown from "react-markdown";
import { auth, googleProvider } from "./firebase";

// Gemini output often contains markdown (bold, bullet lists, etc.) — render
// it instead of showing literal asterisks. react-markdown renders straight
// to React elements (no dangerouslySetInnerHTML), so this stays XSS-safe.
const markdownComponents = {
  p: ({ children }) => <p style={{ margin: "0 0 8px" }}>{children}</p>,
  ul: ({ children }) => <ul style={{ margin: "4px 0 8px", paddingLeft: 20 }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ margin: "4px 0 8px", paddingLeft: 20 }}>{children}</ol>,
  li: ({ children }) => <li style={{ margin: "2px 0" }}>{children}</li>,
  code: ({ children }) => (
    <code style={{ background: "rgba(0,0,0,0.06)", padding: "1px 5px", borderRadius: 4, fontSize: "0.9em" }}>
      {children}
    </code>
  ),
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>
      {children}
    </a>
  ),
};

function Markdown({ children }) {
  return <ReactMarkdown components={markdownComponents}>{children}</ReactMarkdown>;
}

// In production the API is served by Vercel functions on the same origin;
// in local dev the FastAPI server runs separately on port 8000.
const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");

// Vercel serverless functions reject bodies over ~4.5 MB.
const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

const MOCK = {
  title: "Chapter 6 — Memory & Learning",
  summary: [
    "Memory operates in three stages: encoding (taking information in), storage (holding it over time), and retrieval (bringing it back).",
    "Working memory is limited to roughly 4–7 items, which is why chunking related information together improves recall.",
    "Spaced repetition — reviewing material at increasing intervals — produces far stronger long-term retention than cramming.",
    "Active recall (testing yourself) outperforms passive review (re-reading) because the effort of retrieval strengthens the memory trace.",
  ],
  quiz: [
    {
      q: "Which study technique produces the strongest long-term retention?",
      options: ["Re-reading notes", "Highlighting", "Spaced repetition", "Listening passively"],
      answer: 2,
      topic: "Spaced repetition",
    },
    {
      q: "Roughly how many items can working memory hold at once?",
      options: ["1–2", "4–7", "10–12", "20+"],
      answer: 1,
      topic: "Working memory",
    },
    {
      q: "Why does active recall beat passive review?",
      options: [
        "It takes less time",
        "Retrieval effort strengthens the memory trace",
        "It feels easier",
        "It uses more colour",
      ],
      answer: 1,
      topic: "Active recall",
    },
  ],
  podcast: {
    duration: "10:00",
    hosts: ["Maya", "Theo"],
    transcript: [
      { t: "0:00", who: "Maya", line: "Welcome back. Today we're working through Chapter 6 — Memory and Learning. Theo, where do you want to start?" },
      { t: "0:14", who: "Theo", line: "Let's start with the three stages, because everything else builds on them: encoding, storage, and retrieval." },
      { t: "0:41", who: "Maya", line: "Right — encoding is taking the information in, storage is holding it over time, and retrieval is pulling it back out when you need it." },
      { t: "1:38", who: "Theo", line: "And the interesting limit is working memory. You can only juggle about four to seven items at once." },
      { t: "2:55", who: "Maya", line: "Which is exactly why chunking helps — grouping related bits into one unit so it counts as a single item instead of five." },
      { t: "4:20", who: "Theo", line: "Now the big one for exam season: spaced repetition beats cramming, and it isn't close." },
      { t: "6:02", who: "Maya", line: "Because each review lands right as you're about to forget — that effortful recall is what strengthens the trace." },
      { t: "7:48", who: "Theo", line: "Same reason active recall beats re-reading. Testing yourself feels harder, and that difficulty is the point." },
      { t: "9:10", who: "Maya", line: "So the takeaway: space it out, test yourself, chunk what you can. That's the chapter. See you next time." },
    ],
  },
};

const STEPS = [
  { id: "summary", label: "Summary", icon: Sparkles },
  { id: "quiz", label: "Quiz", icon: ListChecks },
  { id: "cards", label: "Cards", icon: Layers },
  { id: "podcast", label: "Podcast", icon: Headphones },
  { id: "tutor", label: "Tutor", icon: MessageCircle },
];

function friendlyAuthError(code) {
  switch (code) {
    case "auth/invalid-email":
      return "That doesn't look like a valid email address.";
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "Incorrect email or password.";
    case "auth/too-many-requests":
      return "Too many attempts. Please wait a moment and try again.";
    case "auth/popup-blocked":
      return "Your browser blocked the sign-in popup. Please allow popups for this site and try again.";
    case "auth/account-exists-with-different-credential":
      return "An account already exists with this email using a different sign-in method.";
    case "auth/operation-not-allowed":
      return "Google sign-in isn't turned on for this app yet. Enable it in Firebase Console → Authentication → Sign-in method.";
    case "auth/unauthorized-domain":
      return "This site's domain isn't authorized for sign-in yet. Add it in Firebase Console → Authentication → Settings → Authorized domains.";
    case "auth/configuration-not-found":
      return "Sign-in isn't fully configured for this Firebase project yet.";
    default:
      // Unrecognized codes are rare enough that showing the raw code beats
      // a silent generic message — it's the fastest way to diagnose a new
      // one without needing to reproduce it with browser devtools open.
      return code ? `Something went wrong (${code}). Please try again.` : "Something went wrong. Please try again.";
  }
}

// The Syrora mark: a rounded moss tile with a white "S" built from plain
// shapes (not text) so it stays crisp at favicon sizes regardless of which
// fonts are installed, plus a small amber dot — a spark of insight adapting
// to the learner. Used both in the app header and as the browser-tab
// favicon (public/favicon.svg mirrors this exact design).
function SyroraMark({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <rect width="64" height="64" rx="16" fill={moss} />
      <rect x="16" y="15" width="30" height="8" rx="3" fill="#fff" />
      <rect x="16" y="28" width="30" height="8" rx="3" fill="#fff" />
      <rect x="16" y="41" width="30" height="8" rx="3" fill="#fff" />
      <rect x="16" y="15" width="8" height="21" rx="3" fill="#fff" />
      <rect x="38" y="28" width="8" height="21" rx="3" fill="#fff" />
      <circle cx="52" cy="52" r="5" fill={amber} />
    </svg>
  );
}

// Bump this when the banner's message changes materially — dismissing an
// old version shouldn't silently suppress a genuinely new notice.
const EARLY_ACCESS_BANNER_KEY = "syrora_early_access_banner_dismissed_v1";

function EarlyAccessBanner({ onGiveFeedback, onDismiss }) {
  return (
    <div style={styles.bannerBar} role="note">
      <p style={styles.bannerText}>
        <strong>Early Access:</strong> Syrora is evolving quickly. We'd love your feedback as we build new features.
      </p>
      {onGiveFeedback && (
        <button style={styles.bannerBtn} onClick={onGiveFeedback}>
          <MessageSquarePlus size={14} /> Give feedback
        </button>
      )}
      <button style={styles.bannerClose} onClick={onDismiss} aria-label="Dismiss this notice">
        <X size={15} />
      </button>
    </div>
  );
}

function FeedbackModal({ onClose, authedFetch, context }) {
  const [rating, setRating] = useState(0);
  const [hoverRating, setHoverRating] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (rating === 0) {
      setError("Pick a star rating first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await authedFetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, comment, context }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || `Could not send feedback (error ${res.status}).`);
      }
      setSent(true);
    } catch (err) {
      setError(
        err instanceof TypeError ? "Could not reach the study service. Please try again in a moment." : err.message
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={styles.modalOverlay}
      onClick={onClose}
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <div
        className="fade"
        style={styles.modalCard}
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <h3 id="feedback-title" style={{ ...styles.panelH, marginBottom: 6 }}>
            {sent ? "Thank you." : "Give feedback"}
          </h3>
          <button style={styles.modalClose} onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {sent ? (
          <>
            <p style={styles.resultSub}>Your feedback was sent. It goes straight to the person building this.</p>
            <button style={styles.primaryBtn} onClick={onClose}>
              Done
            </button>
          </>
        ) : (
          <form onSubmit={submit}>
            <p style={{ ...styles.resultSub, margin: "0 0 14px" }}>
              What's working, what isn't: a star rating and a line or two is plenty.
            </p>
            <div style={styles.starRow} role="radiogroup" aria-label="Rating out of 5 stars">
              {[1, 2, 3, 4, 5].map((n) => {
                const filled = n <= (hoverRating || rating);
                return (
                  <button
                    key={n}
                    type="button"
                    style={styles.starBtn}
                    role="radio"
                    aria-checked={rating === n}
                    aria-label={`${n} star${n > 1 ? "s" : ""}`}
                    onClick={() => setRating(n)}
                    onMouseEnter={() => setHoverRating(n)}
                    onMouseLeave={() => setHoverRating(0)}
                  >
                    <Star size={26} fill={filled ? amber : "none"} stroke={filled ? amber : line} strokeWidth={1.6} />
                  </button>
                );
              })}
            </div>
            <label htmlFor="feedback-comment" style={styles.feedbackLabel}>
              Comments (optional)
            </label>
            <textarea
              id="feedback-comment"
              style={styles.feedbackTextarea}
              placeholder="Anything you'd want to tell me directly…"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={4}
              maxLength={2000}
            />
            {error && (
              <p style={styles.errorText} role="alert">
                {error}
              </p>
            )}
            <button
              type="submit"
              style={{ ...styles.primaryBtn, width: "100%", justifyContent: "center", opacity: busy ? 0.6 : 1 }}
              disabled={busy}
            >
              {busy ? "Sending…" : "Send feedback"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

// The standard four-color "G" glyph Google's own branding guidelines
// specify for third-party "Sign in with Google" buttons — not the Syrora
// mark, so it keeps its real colors regardless of theme.
function GoogleIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#4285F4" d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z" />
      <path fill="#34A853" d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z" />
      <path fill="#FBBC05" d="M11.69 28.18A13.89 13.89 0 0 1 10.9 24c0-1.45.25-2.86.69-4.18v-5.7H4.34A21.93 21.93 0 0 0 2 24c0 3.55.85 6.91 2.34 9.88l7.35-5.7z" />
      <path fill="#EA4335" d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z" />
    </svg>
  );
}

function AuthScreen({ blockedMessage }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await signInWithEmailAndPassword(auth, email, password);
    } catch (err) {
      setError(friendlyAuthError(err.code));
    } finally {
      setBusy(false);
    }
  };

  const submitGoogle = async () => {
    setError("");
    setBusy(true);
    try {
      await signInWithPopup(auth, googleProvider);
    } catch (err) {
      // The user closing the popup or triggering a second one isn't an
      // error worth surfacing — every other failure gets the normal message.
      if (err.code !== "auth/popup-closed-by-user" && err.code !== "auth/cancelled-popup-request") {
        setError(friendlyAuthError(err.code));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <main id="main-content" className="upload-wrap" style={styles.uploadWrap}>
      <p style={styles.eyebrow}>Knowledge that adapts to every mind.</p>
      <h1 className="hero-title" style={styles.h1}>
        Turn any document into a{" "}<br />
        <span style={styles.h1accent}>study session.</span>
      </h1>
      <p className="hero-sub" style={styles.sub}>
        This app is invite-only. Sign in with your account to continue.
      </p>
      <form onSubmit={submit} style={styles.authForm}>
        <h2 style={styles.authTitle}>Sign in</h2>
        <button
          type="button"
          className="google-btn"
          style={{ ...styles.googleBtn, opacity: busy ? 0.6 : 1 }}
          onClick={submitGoogle}
          disabled={busy}
        >
          <GoogleIcon size={18} /> Continue with Google
        </button>
        <div style={styles.authDivider} aria-hidden="true">
          <span style={styles.authDividerLine} />
          <span style={styles.authDividerText}>or</span>
          <span style={styles.authDividerLine} />
        </div>
        <input
          style={styles.chatInput}
          type="email"
          required
          placeholder="Email"
          aria-label="Email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          style={styles.chatInput}
          type="password"
          required
          minLength={6}
          placeholder="Password"
          aria-label="Password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {(error || blockedMessage) && (
          <p style={styles.errorText} role="alert">{error || blockedMessage}</p>
        )}
        <button
          type="submit"
          style={{ ...styles.primaryBtn, width: "100%", justifyContent: "center", opacity: busy ? 0.6 : 1 }}
          disabled={busy}
        >
          {busy ? "Please wait…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

export default function StudyMVP() {
  // undefined = still checking the session, null = signed out
  const [user, setUser] = useState(undefined);
  const [stage, setStage] = useState("upload");
  const [tab, setTab] = useState("summary");
  const [fileName, setFileName] = useState("");
  const [loading, setLoading] = useState(false);
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState("");
  const [history, setHistory] = useState([]);
  // True until the first history fetch after sign-in resolves — it has to
  // wait for Firebase auth and often a serverless cold start, so the list
  // can take a few seconds. The upload screen shows a loading row instead
  // of popping the list in late (or showing nothing when there's none).
  const [historyLoading, setHistoryLoading] = useState(true);
  const [profile, setProfile] = useState(null);
  // Briefly true right after usage_today changes, so the badge can pulse
  // instead of silently jumping to a new number.
  const [usagePulse, setUsagePulse] = useState(false);
  const prevUsageRef = useRef(null);
  const [blockedMessage, setBlockedMessage] = useState("");
  const [showBanner, setShowBanner] = useState(
    () => typeof window === "undefined" || localStorage.getItem(EARLY_ACCESS_BANNER_KEY) !== "1"
  );
  const [showFeedback, setShowFeedback] = useState(false);
  // Config flags read from the backend (an env var, not a per-user
  // setting) — e.g. whether the free browser-voice podcast player is
  // enabled. Defaults to false/hidden until the fetch resolves.
  const [browserVoiceEnabled, setBrowserVoiceEnabled] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => onAuthStateChanged(auth, setUser), []);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = await res.json().catch(() => null);
        if (res.ok && data) setBrowserVoiceEnabled(!!data.browser_voice_enabled);
      } catch {
        // Config fetch failed — keep the safe default (hidden).
      }
    })();
  }, []);

  const dismissBanner = () => {
    setShowBanner(false);
    localStorage.setItem(EARLY_ACCESS_BANNER_KEY, "1");
  };

  const authedFetch = async (path, options = {}) => {
    const token = await auth.currentUser.getIdToken();
    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
    });
    if (res.status === 403) {
      const data = await res.clone().json().catch(() => null);
      setBlockedMessage(data?.detail || "You don't have access to this app.");
      await signOut(auth);
    }
    // Every AI action that spends a usage unit is a POST — refreshing the
    // usage badge here (once, centrally) means it stays live without
    // threading a refresh call through every panel that can trigger one.
    if (res.ok && (options.method || "GET").toUpperCase() === "POST" && path !== "/api/feedback") {
      refreshProfile();
    }
    return res;
  };

  const refreshHistory = async () => {
    try {
      const res = await authedFetch("/api/documents");
      const data = await res.json().catch(() => null);
      if (res.ok) setHistory(data.documents);
    } catch {
      // best-effort — history list isn't critical path
    } finally {
      setHistoryLoading(false);
    }
  };

  const refreshProfile = async () => {
    try {
      const res = await authedFetch("/api/profile");
      const data = await res.json().catch(() => null);
      if (res.ok && data) {
        if (prevUsageRef.current !== null && data.usage_today !== prevUsageRef.current) {
          setUsagePulse(true);
          setTimeout(() => setUsagePulse(false), 700);
        }
        prevUsageRef.current = data.usage_today;
        setProfile(data);
      }
    } catch {
      // best-effort
    }
  };

  useEffect(() => {
    if (user) {
      setBlockedMessage("");
      setHistoryLoading(true);
      refreshHistory();
      refreshProfile();
    } else {
      setHistory([]);
      setHistoryLoading(true);
      setProfile(null);
      prevUsageRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const openHistoryEntry = async (entry) => {
    setError("");
    setFileName(entry.file_name);
    setLoading(true);

    // The history list is metadata-only; the stored document text is
    // fetched per-document so Tutor chat works on reopened documents.
    // Entries saved before text storage existed simply come back empty.
    let context = null;
    let detail = null;
    try {
      const res = await authedFetch(`/api/documents/${entry.id}`);
      const data = await res.json().catch(() => null);
      if (res.ok && data) detail = data;
      if (detail?.document_context) context = detail.document_context;
    } catch {
      // fall through — tutor shows the re-upload notice instead
    }

    setDoc({
      title: entry.title,
      summary: entry.summary,
      quiz: entry.quiz,
      podcast: entry.podcast,
      documentContext: context,
      fromHistory: true,
      docFileName: entry.file_name,
      documentId: entry.id,
      podcastStyle: detail?.podcast_style,
      savedStyles: detail?.saved_styles,
    });
    setLoading(false);
    setStage("study");
    setTab("summary");
  };

  const deleteHistoryEntry = async (id, e) => {
    e.stopPropagation();
    setHistory((prev) => prev.filter((h) => h.id !== id));
    try {
      await authedFetch(`/api/documents/${id}`, { method: "DELETE" });
    } catch {
      refreshHistory();
    }
  };

  const clearAllHistory = async () => {
    setHistory([]);
    try {
      await authedFetch("/api/documents", { method: "DELETE" });
    } catch {
      refreshHistory();
    }
  };

  const startUpload = async (file) => {
    setError("");

    if (!file) {
      // Sample mode: show bundled demo content without hitting the backend.
      setFileName("psychology-ch6.pdf");
      setLoading(true);
      setTimeout(() => {
        setDoc({ ...MOCK, documentContext: null, docFileName: null });
        setLoading(false);
        setStage("study");
        setTab("summary");
      }, 1400);
      return;
    }

    if (file.size > MAX_UPLOAD_BYTES) {
      setError("PDF is too large. Maximum supported size is 4 MB.");
      return;
    }

    setFileName(file.name);
    setLoading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await authedFetch("/api/pdf/analyze", { method: "POST", body: form });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(data?.detail || `The study service returned an error (${res.status}).`);
      }
      setDoc({
        title: data.title,
        summary: data.summary,
        quiz: data.quiz,
        podcast: data.podcast,
        documentContext: data.document_context,
        docFileName: data.file_name,
        documentId: data.document_id,
        podcastStyle: data.podcast_style,
        savedStyles: data.saved_styles,
      });
      refreshHistory();
      refreshProfile();
      setStage("study");
      setTab("summary");
    } catch (err) {
      setError(
        err instanceof TypeError
          ? "Could not reach the study service. Please try again in a moment."
          : err.message
      );
    } finally {
      setLoading(false);
    }
  };

  const trend = weeklyStudyTrend(history);

  if (user === undefined) {
    return (
      <div className="app-shell" style={styles.app}>
        <style>{css}</style>
        <main
          id="main-content"
          style={{ ...styles.uploadWrap, alignItems: "center", justifyContent: "center" }}
          role="status"
          aria-live="polite"
          aria-label="Checking your session"
        >
          <div className="spinner" aria-hidden="true" />
        </main>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="app-shell" style={styles.app}>
        <style>{css}</style>
        <a href="#main-content" className="skip-link">Skip to content</a>
        <header className="app-header" style={styles.header}>
          <div style={styles.brand}>
            <SyroraMark size={32} />
            <span style={styles.brandName}>Syrora</span>
          </div>
        </header>
        <AuthScreen blockedMessage={blockedMessage} />
      </div>
    );
  }

  return (
    <div className="app-shell" style={styles.app}>
      <style>{css}</style>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <header className="app-header" style={styles.header}>
        <div style={styles.brand}>
          <SyroraMark size={32} />
          <span style={styles.brandName}>Syrora</span>
          <span className="brand-tagline" style={styles.brandTagline}>Knowledge that adapts to every mind.</span>
        </div>
        <div style={styles.headerRight}>
          {trend && (
            <span
              className="trend-badge"
              style={{ ...styles.trendBadge, color: trend.delta < 0 ? muted : mossDeep }}
            >
              {trend.delta > 0 ? (
                <TrendingUp size={13} aria-hidden="true" />
              ) : trend.delta < 0 ? (
                <TrendingDown size={13} aria-hidden="true" />
              ) : (
                <Minus size={13} aria-hidden="true" />
              )}
              {trend.thisWeek} {trend.thisWeek === 1 ? "session" : "sessions"} this week
            </span>
          )}
          {profile && (
            <span className={`usage-badge ${usagePulse ? "usage-badge-pulse" : ""}`} style={styles.usageBadge}>
              {profile.usage_today}/{profile.daily_limit} today
            </span>
          )}
          {stage === "study" && (
            <button style={styles.resetBtn} onClick={() => setStage("upload")}>
              <RotateCcw size={14} /> New upload
            </button>
          )}
          <button style={styles.resetBtn} onClick={() => signOut(auth)} title={user.email}>
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </header>

      {showBanner && (
        <EarlyAccessBanner onGiveFeedback={() => setShowFeedback(true)} onDismiss={dismissBanner} />
      )}

      {stage === "upload" ? (
        <UploadScreen
          loading={loading}
          onUpload={startUpload}
          fileRef={fileRef}
          error={error}
          history={history}
          historyLoading={historyLoading}
          onOpenHistory={openHistoryEntry}
          onDeleteHistory={deleteHistoryEntry}
          onClearHistory={clearAllHistory}
        />
      ) : (
        <StudyScreen
          tab={tab}
          setTab={setTab}
          fileName={fileName}
          doc={doc}
          authedFetch={authedFetch}
          browserVoiceEnabled={browserVoiceEnabled}
        />
      )}

      {showFeedback && (
        <FeedbackModal
          onClose={() => setShowFeedback(false)}
          authedFetch={authedFetch}
          context={stage === "study" ? tab : stage}
        />
      )}
    </div>
  );
}

function formatHistoryDate(iso) {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Real, honest trend from the documents already loaded into history — no
// fabricated numbers. Counts study sessions (documents opened/analyzed) in
// the last 7 days against the 7 days before that. Returns null when there's
// no activity yet this week — a 0-count badge with a down arrow would read
// as a guilt trip, not a neutral stat, so it's better to show nothing.
const DAY_MS = 24 * 60 * 60 * 1000;
function weeklyStudyTrend(history) {
  if (!history || history.length === 0) return null;
  const now = Date.now();
  let thisWeek = 0;
  let lastWeek = 0;
  for (const entry of history) {
    const age = now - new Date(entry.created_at).getTime();
    if (Number.isNaN(age)) continue;
    if (age >= 0 && age < 7 * DAY_MS) thisWeek++;
    else if (age >= 7 * DAY_MS && age < 14 * DAY_MS) lastWeek++;
  }
  if (thisWeek === 0) return null;
  const delta = thisWeek - lastWeek;
  return { thisWeek, delta };
}

// Shared between the desktop sidebar and the mobile inline block — which of
// the two containers is visible is decided purely in CSS (min-width: 1100px).
// Renders nothing once loading is done and there's no history to show.
function HistoryPanel({ history, historyLoading, onOpenHistory, onDeleteHistory, onClearHistory }) {
  if (!historyLoading && history.length === 0) return null;
  return (
    <>
      <div style={styles.historyHead}>
        <span style={styles.historyTitle}>
          <Clock size={13} /> Recent documents
        </span>
        {history.length > 0 && (
          <button style={styles.historyClear} onClick={onClearHistory}>
            Clear all
          </button>
        )}
      </div>
      {history.length === 0 ? (
        <div style={styles.historyLoading} role="status" aria-live="polite">
          <div className="spinner spinner-sm" aria-hidden="true" />
          Loading your documents…
        </div>
      ) : (
        <div style={styles.historyList}>
          {history.map((entry) => (
            <div key={entry.id} className="history-item" style={styles.historyItem} onClick={() => onOpenHistory(entry)}>
              <FileText size={15} style={{ color: muted, flexShrink: 0 }} />
              <div style={styles.historyMeta}>
                <p style={styles.historyDocTitle}>{entry.title}</p>
                <p style={styles.historyFileName}>{entry.file_name}</p>
              </div>
              <span style={styles.historyDate}>{formatHistoryDate(entry.created_at)}</span>
              <button
                style={styles.historyDelete}
                onClick={(e) => onDeleteHistory(entry.id, e)}
                aria-label={`Remove ${entry.file_name} from history`}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function UploadScreen({ loading, onUpload, fileRef, error, history, historyLoading, onOpenHistory, onDeleteHistory, onClearHistory }) {
  const [drag, setDrag] = useState(false);
  const hasHistoryPanel = historyLoading || history.length > 0;
  const historyPanel = (
    <HistoryPanel
      history={history}
      historyLoading={historyLoading}
      onOpenHistory={onOpenHistory}
      onDeleteHistory={onDeleteHistory}
      onClearHistory={onClearHistory}
    />
  );

  return (
    <main
      id="main-content"
      className={`upload-wrap ${hasHistoryPanel ? "has-sidebar" : ""}`}
      style={styles.uploadWrap}
    >
      {hasHistoryPanel && (
        <aside className="history-sidebar" aria-label="Recent documents">
          <div className="history-sidebar-body">{historyPanel}</div>
        </aside>
      )}
      <div className="upload-main">
      <p style={styles.eyebrow}>Knowledge that adapts to every mind.</p>
      <h1 className="hero-title" style={styles.h1}>
        Turn any document into a{" "}<br />
        <span style={styles.h1accent}>study session.</span>
      </h1>
      <p className="hero-sub" style={styles.sub}>
        Drop in your lecture notes or slides. Get a clean summary, a quiz that
        finds your weak spots, and a tutor that only knows your material.
      </p>

      <div
        className={`dropzone ${drag ? "drag" : ""} ${loading ? "loading" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onUpload(f);
        }}
        onClick={() => !loading && fileRef.current?.click()}
        onKeyDown={(e) => {
          if (loading) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileRef.current?.click();
          }
        }}
        role="button"
        tabIndex={0}
        aria-label="Drop a PDF here or click to browse, max file size 4 MB"
      >
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,application/pdf"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
            e.target.value = "";
          }}
        />
        {loading ? (
          <div style={styles.loadingBox} role="status" aria-live="polite">
            <div className="spinner" aria-hidden="true" />
            <p style={styles.loadingText}>Reading your document…</p>
            <p style={styles.loadingSub}>Generating summary & quiz</p>
          </div>
        ) : (
          <>
            <div style={styles.uploadIcon}>
              <Upload size={26} strokeWidth={2} />
            </div>
            <p style={styles.dropTitle}>Drop a PDF here</p>
            <p style={styles.dropSub}>or click to browse · PDF, slides, notes</p>
            <p style={styles.dropLimit}>Max file size: 4 MB</p>
          </>
        )}
      </div>

      {!loading && error && <p style={styles.errorText} role="alert">{error}</p>}

      {!loading && (
        <button style={styles.sampleBtn} onClick={() => onUpload(null)}>
          <FileText size={14} /> Try it with a sample document
          <ArrowRight size={14} />
        </button>
      )}

      {!loading && hasHistoryPanel && (
        <div className="history-inline" style={styles.historyBox}>
          {historyPanel}
        </div>
      )}
      </div>
    </main>
  );
}

function StudyScreen({ tab, setTab, fileName, doc, authedFetch, browserVoiceEnabled }) {
  return (
    <main id="main-content" className="study-wrap" style={styles.studyWrap}>
      <div className="doc-header" style={styles.docHeader}>
        <div style={styles.docChip}>
          <FileText size={14} />
          {fileName}
        </div>
        <h2 className="doc-title" style={styles.docTitle}>{doc.title}</h2>
      </div>

      <nav className="tabs" style={styles.tabs} aria-label="Study sections">
        {STEPS.map((s) => {
          const Icon = s.icon;
          const active = tab === s.id;
          return (
            <button
              key={s.id}
              className={`tab ${active ? "active" : ""}`}
              onClick={() => setTab(s.id)}
            >
              <Icon size={18} strokeWidth={2.1} />
              {s.label}
            </button>
          );
        })}
      </nav>

      <section className="panel" style={styles.panel}>
        {tab === "summary" && <SummaryPanel doc={doc} documentId={doc.documentId} authedFetch={authedFetch} />}
        {tab === "quiz" && <QuizPanel doc={doc} documentId={doc.documentId} authedFetch={authedFetch} />}
        {tab === "cards" && <FlashcardsPanel documentId={doc.documentId} authedFetch={authedFetch} />}
        {tab === "podcast" && (
          <PodcastPanel
            doc={doc}
            documentId={doc.documentId}
            authedFetch={authedFetch}
            browserVoiceEnabled={browserVoiceEnabled}
          />
        )}
        {tab === "tutor" && (
          <TutorPanel
            documentContext={doc.documentContext}
            documentId={doc.documentId}
            docFileName={doc.docFileName}
            fromHistory={doc.fromHistory}
            authedFetch={authedFetch}
          />
        )}
      </section>
    </main>
  );
}

// Shared "regenerate in a different way" control, used by Summary and
// Podcast so both tabs read identically: a labelled row of tappable action
// buttons (not a toggle) where one tap starts generation, the tapped button
// shows a spinner, and the option currently applied is marked "current".
function RegenActions({ heading, options, activeId, busyId, disabled, onPick, savedIds = [] }) {
  return (
    <div style={styles.regenSection}>
      <p style={styles.regenHeading}>{heading}</p>
      <div style={styles.regenActions}>
        {options.map((opt) => {
          const isBusy = busyId === opt.id;
          const isCurrent = activeId === opt.id;
          // A saved option loads instantly from storage — no AI call — so it
          // shows a history icon instead of the AI-generation sparkle.
          const isSaved = savedIds.includes(opt.id);
          return (
            <button
              key={opt.id}
              style={{
                ...styles.regenActionBtn,
                ...(isCurrent ? styles.regenActionBtnCurrent : {}),
                opacity: disabled && !isBusy ? 0.5 : 1,
                cursor: disabled ? "default" : "pointer",
              }}
              onClick={() => onPick(opt.id)}
              disabled={disabled}
            >
              {isBusy ? (
                <span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} aria-hidden="true" />
              ) : isCurrent ? (
                <Check size={14} strokeWidth={2.6} />
              ) : isSaved ? (
                <History size={14} />
              ) : (
                <Sparkles size={14} />
              )}
              {isBusy ? (isSaved ? "Loading…" : "Generating…") : opt.label}
              {isCurrent && !isBusy && <span style={styles.regenCurrentTag}>current</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

const SUMMARY_LENGTHS = [
  { id: "concise", label: "Concise" },
  { id: "detailed", label: "Detailed" },
];

function SummaryPanel({ doc, documentId, authedFetch }) {
  // Local copy so regenerating never overwrites doc.summary — matches the
  // same pattern QuizPanel uses for its active question set.
  const [summary, setSummary] = useState(doc.summary);
  const [length, setLength] = useState("concise");
  const [focus, setFocus] = useState("");
  // Which option is currently generating ("concise" / "detailed" / "focus"),
  // so the spinner shows inside the control that was tapped.
  const [busyWith, setBusyWith] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setSummary(doc.summary);
    setError("");
  }, [doc]);

  // One tap = generate. `busyKey` marks which control shows the spinner
  // ("concise" / "detailed" for the length buttons, "focus" for the topic
  // field). Length buttons summarise the whole document; the focus field
  // summarises just the typed topic — the two actions never overlap.
  const regenerate = async (nextLength, focusText, busyKey) => {
    if (busyWith) return;
    setBusyWith(busyKey);
    setError("");
    try {
      const res = await authedFetch(`/api/documents/${documentId}/summary/regenerate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ length: nextLength, focus: focusText }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || `Could not generate a new summary (error ${res.status}).`);
      setLength(nextLength);
      setSummary(data.summary);
    } catch (err) {
      setError(
        err instanceof TypeError ? "Could not reach the study service. Please try again in a moment." : err.message
      );
    } finally {
      setBusyWith(null);
    }
  };

  return (
    <div className="fade">
      <h3 style={styles.panelH}>Key points</h3>
      <ul style={styles.summaryList}>
        {summary.map((point, i) => (
          <li key={i} style={styles.summaryItem}>
            <span style={styles.summaryNum}>{String(i + 1).padStart(2, "0")}</span>
            <span><Markdown>{point}</Markdown></span>
          </li>
        ))}
      </ul>

      {documentId && (
        <div style={styles.regenBox}>
          <RegenActions
            heading="Regenerate summary"
            options={SUMMARY_LENGTHS}
            activeId={length}
            busyId={busyWith}
            disabled={!!busyWith}
            // Length buttons cover the whole document (no focus topic).
            onPick={(id) => regenerate(id, "", id)}
          />

          <div style={styles.focusBlock}>
            <p style={styles.focusLabel}>Or focus on one topic</p>
            <form
              style={styles.focusInputRow}
              onSubmit={(e) => {
                e.preventDefault();
                if (focus.trim()) regenerate(length, focus.trim(), "focus");
              }}
            >
              <input
                style={styles.focusInput}
                placeholder="e.g. maturity benefits, Option 2"
                aria-label="Focus topic to summarize"
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
                maxLength={200}
                disabled={!!busyWith}
              />
              <button
                type="submit"
                style={{ ...styles.focusGenBtn, opacity: busyWith || !focus.trim() ? 0.5 : 1, cursor: busyWith || !focus.trim() ? "default" : "pointer" }}
                disabled={!!busyWith || !focus.trim()}
              >
                {busyWith === "focus" ? (
                  <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} aria-hidden="true" />
                ) : (
                  <Sparkles size={15} />
                )}
                Generate
              </button>
            </form>
          </div>
          {error && <p style={{ ...styles.resultSub, margin: "12px 0 0", color: "#b03d2e" }}>{error}</p>}
        </div>
      )}
    </div>
  );
}

function QuizPanel({ doc, documentId, authedFetch }) {
  // The active question set starts as whatever was stored with the
  // document, but can be swapped for a freshly generated one without
  // touching doc.quiz — regenerating never overwrites the attempt history.
  const [quiz, setQuiz] = useState(doc.quiz);
  const [answers, setAnswers] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [history, setHistory] = useState([]);
  const [expandedAttempt, setExpandedAttempt] = useState(null);
  const [regenerating, setRegenerating] = useState(false);
  const [regenError, setRegenError] = useState("");

  useEffect(() => {
    setQuiz(doc.quiz);
    setAnswers({});
    setSubmitted(false);
    setRegenError("");
  }, [doc, documentId]);

  useEffect(() => {
    if (!documentId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch(`/api/documents/${documentId}/quiz/attempts`);
        if (!res.ok) return;
        const data = await res.json().catch(() => null);
        if (!cancelled && data) setHistory(data.attempts || []);
      } catch {
        // best-effort — history just won't show
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const score = quiz.reduce((n, q, i) => (answers[i] === q.answer ? n + 1 : n), 0);
  const weak = quiz.filter((q, i) => answers[i] !== q.answer).map((q) => q.topic);

  const submit = () => {
    setSubmitted(true);
    if (!documentId) return;
    // Storage only — recording the attempt doesn't call any paid API.
    authedFetch(`/api/documents/${documentId}/quiz/attempts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ questions: quiz, answers: quiz.map((_, i) => answers[i]) }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((attempt) => attempt && setHistory((h) => [attempt, ...h]))
      .catch(() => {});
  };

  const retake = () => {
    setAnswers({});
    setSubmitted(false);
  };

  const regenerate = async () => {
    setRegenerating(true);
    setRegenError("");
    try {
      const res = await authedFetch(`/api/documents/${documentId}/quiz/regenerate`, { method: "POST" });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || `Could not generate a new quiz (error ${res.status}).`);
      setQuiz(data.quiz);
      setAnswers({});
      setSubmitted(false);
    } catch (err) {
      setRegenError(
        err instanceof TypeError ? "Could not reach the quiz service. Please try again in a moment." : err.message
      );
    } finally {
      setRegenerating(false);
    }
  };

  const historySection = history.length > 0 && (
    <div style={styles.quizHistory}>
      <p style={styles.quizHistoryTitle}>Past attempts</p>
      {history.map((a) => (
        <div key={a.id} style={styles.attemptRow}>
          <button style={styles.attemptHeader} onClick={() => setExpandedAttempt(expandedAttempt === a.id ? null : a.id)}>
            <span>{formatHistoryDate(a.created_at)}</span>
            <span>{a.score} / {a.total}</span>
          </button>
          {expandedAttempt === a.id && (
            <div style={styles.attemptDetail}>
              {a.questions.map((q, i) => {
                const correct = a.answers[i] === q.answer;
                return (
                  <p key={i} style={{ ...styles.attemptQ, color: correct ? mossDeep : "#b03d2e" }}>
                    Q{i + 1}. {q.q} — you answered "{q.options[a.answers[i]] ?? "—"}"
                    {!correct && ` (correct: "${q.options[q.answer]}")`}
                  </p>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );

  if (submitted) {
    return (
      <div className="fade" style={styles.resultBox}>
        <div style={styles.scoreRing}>
          <span style={styles.scoreNum}>{score}</span>
          <span style={styles.scoreOf}>/ {quiz.length}</span>
        </div>
        <h3 style={styles.panelH}>
          {score === quiz.length ? "Perfect run." : "Here's where to focus."}
        </h3>
        {weak.length > 0 ? (
          <>
            <p style={styles.resultSub}>Topics to review:</p>
            <div style={styles.weakRow}>
              {weak.map((t, i) => (
                <span key={i} style={styles.weakChip}>{t}</span>
              ))}
            </div>
          </>
        ) : (
          <p style={styles.resultSub}>You nailed every topic in this set.</p>
        )}
        <div style={styles.quizActionRow}>
          <button style={styles.primaryBtn} onClick={retake}>
            <RotateCcw size={15} /> Retake same quiz
          </button>
          {documentId && (
            <button style={{ ...styles.audioBtn, opacity: regenerating ? 0.6 : 1 }} onClick={regenerate} disabled={regenerating}>
              {regenerating ? <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} aria-hidden="true" /> : <Sparkles size={14} />}
              {regenerating ? "Generating…" : "New questions"}
            </button>
          )}
        </div>
        {regenError && <p style={{ ...styles.resultSub, color: "#b03d2e" }} role="alert">{regenError}</p>}
        {historySection}
      </div>
    );
  }

  return (
    <div className="fade">
      <h3 style={styles.panelH}>Quick quiz</h3>
      {quiz.map((q, qi) => (
        <div key={qi} style={styles.qBlock}>
          <p style={styles.qText}>
            <span style={styles.qIndex}>Q{qi + 1}</span>
            {q.q}
          </p>
          <div style={styles.options}>
            {q.options.map((opt, oi) => {
              const picked = answers[qi] === oi;
              return (
                <button
                  key={oi}
                  className={`opt ${picked ? "picked" : ""}`}
                  onClick={() => setAnswers({ ...answers, [qi]: oi })}
                >
                  <span className="optDot" />
                  {opt}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      <button
        style={{
          ...styles.primaryBtn,
          opacity: Object.keys(answers).length === quiz.length ? 1 : 0.45,
        }}
        disabled={Object.keys(answers).length !== quiz.length}
        onClick={submit}
      >
        Check answers <ArrowRight size={15} />
      </button>
      {historySection}
    </div>
  );
}

const PODCAST_STYLES = [
  { id: "conversation", label: "Two hosts" },
  { id: "solo", label: "Solo narrator" },
  { id: "interview", label: "Interview" },
];

// Picks two distinct voices for the two hosts from the browser's built-in
// text-to-speech voices (Web Speech API) — completely free, no API calls,
// no quota, works offline. Voice lists load asynchronously in some browsers
// (Chrome fires `voiceschanged`), so this waits for that if needed.
function pickBrowserVoices() {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    const tryPick = () => {
      const voices = synth.getVoices();
      if (!voices.length) return false;
      const english = voices.filter((v) => v.lang?.toLowerCase().startsWith("en"));
      const pool = english.length >= 2 ? english : voices;
      resolve({ a: pool[0] || null, b: pool[1] || pool[0] || null });
      return true;
    };
    if (tryPick()) return;
    synth.onvoiceschanged = tryPick;
    // Some browsers never fire voiceschanged; fall back to whatever's loaded.
    setTimeout(tryPick, 500);
  });
}

// Sample-mode cards shown when there's no saved document to generate from.
const MOCK_CARDS = [
  { front: "Encoding", back: "Taking information in and converting it into a form memory can store." },
  { front: "Storage", back: "Holding encoded information in memory over time." },
  { front: "Retrieval", back: "Pulling stored information back out of memory when you need it." },
  { front: "Working memory capacity", back: "You can only juggle about four to seven items at once." },
  { front: "Spaced repetition", back: "Reviewing material at increasing intervals — far more effective than cramming." },
  { front: "Active recall", back: "Testing yourself instead of re-reading; the effort of retrieval strengthens the memory trace." },
];

function FlashcardsPanel({ documentId, authedFetch }) {
  // null while the saved sets are loading; [] when there are none yet.
  const [sets, setSets] = useState(null);
  const [setIdx, setSetIdx] = useState(0);
  const [cardIdx, setCardIdx] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setSets(null);
    setSetIdx(0);
    setCardIdx(0);
    setFlipped(false);
    setError("");
    if (!documentId) {
      setSets([]);
      return undefined;
    }
    (async () => {
      try {
        const res = await authedFetch(`/api/documents/${documentId}/flashcards`);
        const data = await res.json().catch(() => null);
        if (!cancelled) setSets(res.ok && Array.isArray(data?.sets) ? data.sets : []);
      } catch {
        if (!cancelled) setSets([]);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  // Generating a new set never deletes the old ones — the backend keeps
  // every previous set and the picker below switches between them.
  const generate = async () => {
    if (busy || !documentId) return;
    setBusy(true);
    setError("");
    try {
      const res = await authedFetch(`/api/documents/${documentId}/flashcards/regenerate`, { method: "POST" });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || `Could not generate flashcards (error ${res.status}).`);
      setSets([data.set, ...(sets || [])]);
      setSetIdx(0);
      setCardIdx(0);
      setFlipped(false);
    } catch (err) {
      setError(
        err instanceof TypeError ? "Could not reach the study service. Please try again in a moment." : err.message
      );
    } finally {
      setBusy(false);
    }
  };

  const usingMock = !documentId;
  const loading = !usingMock && sets === null;
  const cards = usingMock ? MOCK_CARDS : (sets && sets[setIdx]?.cards) || [];
  const card = cards[cardIdx];

  const goTo = (i) => {
    setCardIdx(i);
    setFlipped(false);
  };

  const pickSet = (i) => {
    setSetIdx(i);
    setCardIdx(0);
    setFlipped(false);
  };

  const setLabel = (s, i) => {
    if (i === 0) return "Latest";
    const d = new Date(s.created_at);
    return isNaN(d) ? `Set ${sets.length - i}` : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };

  return (
    <div className="fade">
      <h3 style={{ ...styles.panelH, marginTop: 0 }}>Flashcards</h3>
      <p style={styles.resultSub}>Six cards per set. Tap a card to flip it.</p>

      {loading && (
        <p style={styles.resultSub}>
          <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2, marginRight: 8 }} aria-hidden="true" />
          Loading saved sets…
        </p>
      )}

      {!loading && cards.length === 0 && (
        <div style={{ margin: "18px 0" }}>
          <p style={{ ...styles.resultSub, marginBottom: 14 }}>
            No flashcards yet for this document. Generate a set of six cards grounded in the PDF.
          </p>
          <button style={{ ...styles.audioBtn, opacity: busy ? 0.6 : 1 }} onClick={generate} disabled={busy}>
            {busy ? (
              <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} aria-hidden="true" />
            ) : (
              <Sparkles size={15} />
            )}
            {busy ? "Generating…" : "Generate flashcards"}
          </button>
        </div>
      )}

      {!loading && cards.length > 0 && (
        <>
          {/* key remounts the scene per card, so moving to the next card
              fades in on its front face instead of visibly un-rotating. */}
          <div className="fc-scene fade" key={`${setIdx}-${cardIdx}`}>
            <button
              className={`fc-card ${flipped ? "flipped" : ""}`}
              onClick={() => setFlipped((f) => !f)}
              aria-label={flipped ? "Show the term" : "Reveal the answer"}
            >
              <span className="fc-face">
                <span className="fc-kicker">Card {cardIdx + 1} of {cards.length}</span>
                <span className="fc-term">{card.front}</span>
                <span className="fc-hint">
                  <RotateCcw size={11} /> Tap to reveal the answer
                </span>
              </span>
              <span className="fc-face back">
                <span className="fc-kicker">Answer</span>
                <span className="fc-answer">{card.back}</span>
                <span className="fc-hint">
                  <RotateCcw size={11} /> Tap to flip back
                </span>
              </span>
            </button>
          </div>

          <div className="fc-nav">
            <button
              className="fc-arrow"
              onClick={() => goTo(cardIdx - 1)}
              disabled={cardIdx === 0}
              aria-label="Previous card"
            >
              <ArrowRight size={17} style={{ transform: "rotate(180deg)" }} />
            </button>
            <div className="fc-dots" role="tablist" aria-label="Cards">
              {cards.map((_, i) => (
                <button
                  key={i}
                  className={`fc-dot ${i === cardIdx ? "active" : ""}`}
                  onClick={() => goTo(i)}
                  aria-label={`Go to card ${i + 1}`}
                />
              ))}
            </div>
            <button
              className="fc-arrow"
              onClick={() => goTo(cardIdx + 1)}
              disabled={cardIdx >= cards.length - 1}
              aria-label="Next card"
            >
              <ArrowRight size={17} />
            </button>
          </div>

          {!usingMock && (
            <div style={{ borderTop: "1px solid #e4e0d5", paddingTop: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <button style={{ ...styles.audioBtn, opacity: busy ? 0.6 : 1 }} onClick={generate} disabled={busy}>
                  {busy ? (
                    <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} aria-hidden="true" />
                  ) : (
                    <Sparkles size={15} />
                  )}
                  {busy ? "Generating…" : "New set"}
                </button>
                {sets.length > 1 &&
                  sets.map((s, i) => (
                    <button
                      key={s.id || i}
                      onClick={() => pickSet(i)}
                      style={{
                        ...styles.audioBtn,
                        padding: "6px 12px",
                        borderColor: i === setIdx ? moss : "#d8d4c8",
                        background: i === setIdx ? "#eef4ef" : "#fff",
                        color: i === setIdx ? mossDeep : "#6b7a70",
                      }}
                    >
                      <History size={13} />
                      {setLabel(s, i)}
                    </button>
                  ))}
              </div>
              <p style={{ ...styles.resultSub, marginTop: 10, fontSize: 12 }}>
                New sets cover different ground; every earlier set stays saved here.
              </p>
            </div>
          )}
        </>
      )}

      {error && <p style={{ ...styles.resultSub, color: "#b03d2e", marginTop: 10 }}>{error}</p>}
    </div>
  );
}

function PodcastPanel({ doc, documentId, authedFetch, browserVoiceEnabled }) {
  // Local copy so regenerating the script never overwrites doc.podcast —
  // same pattern QuizPanel/SummaryPanel use for their own active content.
  const [podcast, setPodcast] = useState(doc.podcast);
  const { duration, hosts, transcript } = podcast;

  const [podcastStyle, setPodcastStyle] = useState(doc.podcastStyle || "conversation");
  // Styles that already have a saved script (and possibly audio) in storage
  // — tapping one of those loads it instead of paying for a new generation.
  const [savedStyles, setSavedStyles] = useState(doc.savedStyles || []);
  // Style id currently being generated (null when idle) — the spinner shows
  // inside the chip that was tapped, since tapping a chip IS the action.
  const [scriptBusy, setScriptBusy] = useState(null);
  const [scriptError, setScriptError] = useState("");

  // AI audio state: idle → generating → ready (or error). There is no
  // simulated/fake playback — the player only appears once real audio
  // exists, so the play button never implies audio that isn't there.
  const [audioState, setAudioState] = useState("idle");
  const [genProgress, setGenProgress] = useState(0);
  const [audioError, setAudioError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [playingIdx, setPlayingIdx] = useState(0);
  const [segProgress, setSegProgress] = useState(0);
  const audioRef = useRef(null);
  // Blob URLs for each segment, indexed by position. Populated eagerly by
  // generateAudio and lazily (from cache) during playback, so it lives in a
  // ref rather than state — playback reads it without forcing re-renders.
  const urlsRef = useRef([]);
  // Episode mode: the whole episode is ONE continuous MP3 track (Google
  // Cloud TTS provider) — a single audio element, real seeking, no gaps.
  // Per-segment clips remain the fallback for the other TTS providers.
  const [episodeMode, setEpisodeMode] = useState(false);
  const episodeUrlRef = useRef(null);

  // Free playback via the browser's built-in voices (Web Speech API) — no
  // backend call, no API cost, no quota, so this would always be available
  // and never error the way the paid AI-audio generation below can. Gated
  // behind browserVoiceEnabled (an env-var-driven config flag, see
  // ENABLE_BROWSER_VOICE in api/index.py) — hidden for now, flip the env
  // var when it's wanted back, no code change required.
  const speechSupported =
    browserVoiceEnabled && typeof window !== "undefined" && "speechSynthesis" in window;
  const [browserPlaying, setBrowserPlaying] = useState(false);
  const [browserIdx, setBrowserIdx] = useState(0);
  const browserVoicesRef = useRef({ a: null, b: null });

  useEffect(() => {
    setPodcast(doc.podcast);
    setPodcastStyle(doc.podcastStyle || "conversation");
    setSavedStyles(doc.savedStyles || []);
    setScriptError("");
    if (speechSupported) window.speechSynthesis.cancel();
    setBrowserPlaying(false);
    setBrowserIdx(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

  useEffect(() => {
    return () => {
      if (speechSupported) window.speechSynthesis.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const speakSegment = async (i) => {
    if (i >= transcript.length) {
      setBrowserPlaying(false);
      setBrowserIdx(0);
      return;
    }
    if (!browserVoicesRef.current.a && !browserVoicesRef.current.b) {
      browserVoicesRef.current = await pickBrowserVoices();
    }
    const seg = transcript[i];
    const utter = new SpeechSynthesisUtterance(seg.line);
    utter.voice = seg.who === hosts[0] ? browserVoicesRef.current.a : browserVoicesRef.current.b;
    utter.rate = 1;
    utter.onend = () => speakSegment(i + 1);
    utter.onerror = (e) => {
      // "interrupted"/"canceled" fire on Stop or skip — not real errors.
      if (e.error !== "interrupted" && e.error !== "canceled") setBrowserPlaying(false);
    };
    setBrowserIdx(i);
    window.speechSynthesis.speak(utter);
  };

  const toggleBrowserVoice = () => {
    if (!speechSupported) return;
    if (browserPlaying) {
      window.speechSynthesis.cancel();
      setBrowserPlaying(false);
      return;
    }
    // Only one voice plays at a time — stop any AI audio first.
    audioRef.current?.pause();
    setPlaying(false);
    setBrowserPlaying(true);
    speakSegment(browserIdx < transcript.length ? browserIdx : 0);
  };

  const jumpBrowserVoice = (i) => {
    if (!speechSupported) return;
    window.speechSynthesis.cancel();
    audioRef.current?.pause();
    setPlaying(false);
    setBrowserPlaying(true);
    speakSegment(i);
  };

  const revokeUrls = () => {
    urlsRef.current.forEach((u) => u && URL.revokeObjectURL(u));
    urlsRef.current = [];
    if (episodeUrlRef.current) {
      URL.revokeObjectURL(episodeUrlRef.current);
      episodeUrlRef.current = null;
    }
  };

  // Char-proportional start position (0..1) of each segment inside the
  // single episode track — used to map playback time to the highlighted
  // transcript line and taps on a line to a seek position.
  const segmentFractions = (pod) => {
    const lengths = pod.transcript.map((seg) => Math.max(seg.line.length, 1));
    const total = lengths.reduce((a, b) => a + b, 0) || 1;
    let acc = 0;
    return lengths.map((len) => {
      const fraction = acc / total;
      acc += len;
      return fraction;
    });
  };

  // Tapping a style chip is the whole flow: generate the new script in that
  // style, then go straight into generating its audio — no separate
  // "New script" / "Generate AI audio" taps needed.
  const regenerateScript = async (style) => {
    if (scriptBusy || audioState === "generating") return;
    setScriptBusy(style);
    setScriptError("");
    try {
      const res = await authedFetch(`/api/documents/${documentId}/podcast/regenerate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || `Could not generate a new script (error ${res.status}).`);
      // The new script no longer lines up with any previously generated
      // audio (the backend already dropped that stale cache), so reset
      // playback state along with swapping in the new transcript. AI audio
      // is NOT auto-generated here — that's a paid/quota-limited call, so
      // it only runs when the user explicitly asks for it below. The free
      // browser-voice player is always ready immediately, no generation step.
      audioRef.current?.pause();
      revokeUrls();
      if (speechSupported) window.speechSynthesis.cancel();
      setPlaying(false);
      setPlayingIdx(0);
      setSegProgress(0);
      setAudioError("");
      setAudioState("idle");
      setBrowserPlaying(false);
      setBrowserIdx(0);
      setPodcastStyle(style);
      setPodcast(data.podcast);
      if (data.saved_styles) setSavedStyles(data.saved_styles);
      setScriptBusy(null);
      setEpisodeMode(false);
      // A reused (saved) version keeps its own audio in storage — if the
      // whole episode is still cached, put the AI player straight back
      // instead of showing the Generate button again.
      if (data.reused && documentId) {
        try {
          const statusRes = await authedFetch(`/api/podcast/audio-status/${documentId}`);
          const status = await statusRes.json().catch(() => null);
          if (status?.episode_cached) {
            const url = await ensureEpisodeUrl();
            startEpisodePlayback(url, data.podcast);
            setEpisodeMode(true);
            setAudioState("ready");
            return;
          }
          const cached = new Set(status?.cached_segments || []);
          const segments = data.podcast?.transcript || [];
          if (segments.length > 0 && segments.every((_, i) => cached.has(i))) {
            urlsRef.current = new Array(segments.length).fill(null);
            setAudioState("ready");
          }
        } catch {
          // Status check failed — leave the player in "idle"; playback
          // would still hit the cache on demand.
        }
      }
    } catch (err) {
      setScriptBusy(null);
      setScriptError(
        err instanceof TypeError ? "Could not reach the study service. Please try again in a moment." : err.message
      );
    }
  };

  // On mount / when switching documents: reset the player, then ask the
  // backend whether saved audio already exists for this document. If every
  // segment is cached, restore the player straight to "ready" — cached
  // playback costs no ElevenLabs calls, so this survives page reloads.
  useEffect(() => {
    let cancelled = false;
    audioRef.current?.pause();
    revokeUrls();
    setPlaying(false);
    setPlayingIdx(0);
    setSegProgress(0);
    setGenProgress(0);
    setAudioError("");
    setAudioState("idle");

    setEpisodeMode(false);

    if (!documentId || transcript.length === 0) return undefined;

    (async () => {
      try {
        const res = await authedFetch(`/api/podcast/audio-status/${documentId}`);
        if (!res.ok) return;
        const data = await res.json();
        // Preferred: a cached single-track episode — fetch it (free cache
        // hit) and restore the player straight to ready.
        if (data.episode_cached) {
          const url = await ensureEpisodeUrl();
          if (!cancelled) {
            startEpisodePlayback(url, podcast);
            setEpisodeMode(true);
            setAudioState("ready");
          }
          return;
        }
        const cached = new Set(data.cached_segments || []);
        // Only restore when the whole episode is cached, so playback never
        // stalls partway through on a segment that was never generated.
        const complete = transcript.every((_, i) => cached.has(i));
        if (!cancelled && complete) {
          urlsRef.current = new Array(transcript.length).fill(null);
          setAudioState("ready");
        }
      } catch {
        // No saved audio reachable — leave the Generate button in place.
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
      revokeUrls();
    };
  }, []);

  // Fetch (or reuse) the blob URL for one segment. A cache hit on the backend
  // returns instantly and is free; only genuinely new audio calls ElevenLabs.
  // `pod` is passed explicitly where the caller may hold a fresher script
  // than the `podcast` state in this render's closure.
  const ensureSegmentUrl = async (i, pod = podcast) => {
    if (urlsRef.current[i]) return urlsRef.current[i];
    const seg = pod.transcript[i];
    const res = await authedFetch("/api/podcast/segment-audio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: seg.line,
        speaker: seg.who === pod.hosts[0] ? 0 : 1,
        // Lets the backend cache/reuse generated audio for this exact
        // document + segment instead of paying for it again next time.
        document_id: documentId || null,
        segment_index: i,
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      const err = new Error(data?.detail || `The audio service returned an error (${res.status}).`);
      err.status = res.status;
      throw err;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    urlsRef.current[i] = url;
    return url;
  };

  const segmentCachedOnServer = async (i) => {
    if (!documentId) return false;
    try {
      const res = await authedFetch(`/api/podcast/audio-status/${documentId}`);
      if (!res.ok) return false;
      const data = await res.json();
      return Array.isArray(data.cached_segments) && data.cached_segments.includes(i);
    } catch {
      return false;
    }
  };

  // A batch generation can take minutes with nothing on the wire, and
  // mobile networks/proxies kill idle connections — but the server keeps
  // generating and CACHES the batch even after the browser's connection
  // drops. So on a network failure (or gateway 5xx), don't give up and
  // don't immediately re-generate: poll the cheap status endpoint until
  // the segment shows up cached, then re-request it as an instant cache
  // hit. Only if it never appears do we retry generation for real.
  const fetchSegmentWithRecovery = async (i, pod) => {
    let lastErr;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        return await ensureSegmentUrl(i, pod);
      } catch (err) {
        lastErr = err;
        const recoverable = err instanceof TypeError || (err.status && err.status >= 500);
        if (!recoverable) throw err;
        for (let poll = 0; poll < 18; poll++) {
          await new Promise((resolve) => setTimeout(resolve, 5000));
          if (await segmentCachedOnServer(i)) break;
        }
      }
    }
    throw lastErr;
  };

  // Fetch the whole episode as ONE MP3 (Google TTS provider). Throws with
  // err.status = 404 when the active provider doesn't offer episode tracks.
  const ensureEpisodeUrl = async () => {
    if (episodeUrlRef.current) return episodeUrlRef.current;
    const res = await authedFetch("/api/podcast/episode-audio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      const err = new Error(data?.detail || `The audio service returned an error (${res.status}).`);
      err.status = res.status;
      throw err;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    episodeUrlRef.current = url;
    return url;
  };

  const episodeCachedOnServer = async () => {
    if (!documentId) return false;
    try {
      const res = await authedFetch(`/api/podcast/audio-status/${documentId}`);
      if (!res.ok) return false;
      const data = await res.json();
      return data.episode_cached === true;
    } catch {
      return false;
    }
  };

  // Same idea as fetchSegmentWithRecovery: the server finishes and caches
  // the track even if our connection drops mid-request, so poll the status
  // endpoint and re-request as a cache hit before re-generating for real.
  const fetchEpisodeWithRecovery = async () => {
    let lastErr;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        return await ensureEpisodeUrl();
      } catch (err) {
        lastErr = err;
        const recoverable = err instanceof TypeError || (err.status && err.status >= 500);
        if (!recoverable) throw err;
        for (let poll = 0; poll < 12; poll++) {
          await new Promise((resolve) => setTimeout(resolve, 5000));
          if (await episodeCachedOnServer()) break;
        }
      }
    }
    throw lastErr;
  };

  // Wire the single episode track into the audio element: overall progress
  // drives the bar directly, and the highlighted transcript line follows
  // the char-proportional segment start positions.
  const startEpisodePlayback = (url, pod, { autoplay } = {}) => {
    if (!audioRef.current) audioRef.current = new Audio();
    const a = audioRef.current;
    const fractions = segmentFractions(pod);
    a.src = url;
    a.ontimeupdate = () => {
      if (!a.duration) return;
      const pct = a.currentTime / a.duration;
      setSegProgress(pct);
      let idx = 0;
      for (let i = 0; i < fractions.length; i++) if (pct >= fractions[i]) idx = i;
      setPlayingIdx(idx);
    };
    a.onended = () => {
      setPlaying(false);
      setPlayingIdx(0);
      setSegProgress(0);
    };
    if (autoplay) {
      a.play();
      setPlaying(true);
    }
  };

  const generateAudioFor = async (pod) => {
    setAudioState("generating");
    setAudioError("");
    setGenProgress(0);
    try {
      urlsRef.current = new Array(pod.transcript.length).fill(null);
      let isEpisode = false;
      if (documentId) {
        // Preferred path: the WHOLE episode as one continuous track in one
        // request (Google Cloud TTS synthesizes it in seconds). A 404 means
        // the active provider only supports per-segment clips.
        try {
          const url = await fetchEpisodeWithRecovery();
          startEpisodePlayback(url, pod);
          isEpisode = true;
        } catch (err) {
          if (err.status !== 404) throw err;
        }
      }
      if (!isEpisode) {
        // Per-segment fallback (Gemini / ElevenLabs providers). Strictly
        // sequential on purpose: a cache miss generates a whole BATCH
        // server-side, so two concurrent misses would each fire an
        // expensive call and trip rate limits.
        for (let i = 0; i < pod.transcript.length; i++) {
          await fetchSegmentWithRecovery(i, pod);
          setGenProgress(i + 1);
        }
      }
      setEpisodeMode(isEpisode);
      // The free browser-voice player is hidden once AI audio is ready, so
      // stop any browser speech now — otherwise it would keep talking with
      // its pause button gone.
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      setBrowserPlaying(false);
      setPlayingIdx(0);
      setSegProgress(0);
      setAudioState("ready");
    } catch (err) {
      setAudioError(
        err instanceof TypeError ? "Could not reach the audio service. Please try again in a moment." : err.message
      );
      setAudioState("error");
    }
  };

  const generateAudio = () => generateAudioFor(podcast);

  // Seek the single episode track to a 0..1 position and play.
  const seekEpisode = (pct) => {
    const a = audioRef.current;
    if (!a || !episodeUrlRef.current) return;
    const seekWhenReady = () => {
      a.currentTime = pct * a.duration;
      a.play();
      setPlaying(true);
    };
    if (a.duration) {
      seekWhenReady();
    } else {
      a.onloadedmetadata = seekWhenReady;
      if (!a.src) a.src = episodeUrlRef.current;
    }
  };

  const playSegment = async (i) => {
    if (episodeMode) {
      seekEpisode(segmentFractions(podcast)[i] ?? 0);
      setPlayingIdx(i);
      return;
    }
    let url;
    try {
      url = await fetchSegmentWithRecovery(i, podcast);
    } catch (err) {
      setPlaying(false);
      setAudioError(
        err instanceof TypeError ? "Could not reach the audio service. Please try again in a moment." : err.message
      );
      setAudioState("error");
      return;
    }
    if (!audioRef.current) audioRef.current = new Audio();
    const a = audioRef.current;
    a.src = url;
    a.ontimeupdate = () => setSegProgress(a.duration ? a.currentTime / a.duration : 0);
    a.onended = () => {
      if (i + 1 < transcript.length) {
        playSegment(i + 1);
      } else {
        setPlaying(false);
        setPlayingIdx(0);
        setSegProgress(0);
      }
    };
    a.play();
    setPlayingIdx(i);
    setSegProgress(0);
    setPlaying(true);
  };

  const toggle = () => {
    // Only one voice plays at a time — stop the free browser voice first.
    if (browserPlaying) {
      window.speechSynthesis.cancel();
      setBrowserPlaying(false);
    }
    const a = audioRef.current;
    if (playing) {
      a?.pause();
      setPlaying(false);
    } else if (a?.src && !a.ended) {
      a.play();
      setPlaying(true);
    } else {
      playSegment(0);
    }
  };

  const audioReady = audioState === "ready";
  // Episode mode has a real continuous timeline; segment mode approximates
  // one from the current clip index + progress within it.
  const progress = episodeMode
    ? Math.min(segProgress * 100, 100)
    : Math.min(((playingIdx + segProgress) / transcript.length) * 100, 100);

  return (
    <div className="fade">
      <div className="pod-hero" style={styles.podHero}>
        <div style={styles.podCover}>
          <Headphones size={30} strokeWidth={1.8} />
        </div>
        <div>
          <p style={styles.podKicker}>{duration.split(":")[0]}-minute episode · {hosts.length} hosts</p>
          <h3 style={styles.podTitle}>{doc.title}</h3>
          <p style={styles.podHosts}>{hosts.join(" & ")} walk through the chapter</p>
        </div>
      </div>

      {documentId && (
        <div style={styles.regenBox}>
          <RegenActions
            heading="Regenerate episode"
            options={PODCAST_STYLES}
            activeId={podcastStyle}
            busyId={scriptBusy}
            disabled={!!scriptBusy || audioState === "generating"}
            onPick={(id) => regenerateScript(id)}
            savedIds={savedStyles}
          />
          {scriptBusy && (
            <p style={styles.regenStatus} role="status" aria-live="polite">Writing a new script…</p>
          )}
          {scriptError && (
            <p style={{ ...styles.resultSub, margin: "12px 0 0", color: "#b03d2e" }} role="alert">{scriptError}</p>
          )}
        </div>
      )}

      {/* Once AI-narrated audio exists, its player below replaces the free
          browser-voice option — two stacked play buttons read as clutter. */}
      {speechSupported && !audioReady && (
        <div className="player" style={styles.player}>
          <button
            style={styles.playBtn}
            onClick={toggleBrowserVoice}
            aria-label={browserPlaying ? "Pause" : "Play"}
          >
            {browserPlaying ? <Pause size={20} /> : <Play size={20} style={{ marginLeft: 2 }} />}
          </button>
          <div style={{ flex: 1 }}>
            <div style={styles.timeRow}>
              <span>{browserPlaying ? `Segment ${browserIdx + 1} / ${transcript.length}` : "Play episode"}</span>
              <span style={styles.freeTag}>Free · your device's voice</span>
            </div>
          </div>
        </div>
      )}

      <div style={styles.audioBar}>
        {audioState === "idle" && (
          <button style={styles.audioBtn} onClick={generateAudio}>
            <Sparkles size={15} /> Generate AI-narrated audio
          </button>
        )}
        {audioState === "generating" && (
          <span style={styles.audioStatus} role="status" aria-live="polite">
            <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} aria-hidden="true" />
            {/* Episode-track generation is one request with no per-segment
                progress to count; the counter only applies to the
                per-segment fallback providers. */}
            Generating audio…{genProgress > 0 ? ` ${genProgress}/${transcript.length}` : ""}
          </span>
        )}
        {audioState === "error" && (
          <span style={{ ...styles.audioStatus, color: "#b03d2e" }} role="alert">
            {audioError}{" "}
            <button style={styles.audioRetry} onClick={generateAudio}>Retry</button>
          </span>
        )}
      </div>

      {audioReady && (
        <div className="player" style={styles.player}>
          <button style={styles.playBtn} onClick={toggle} aria-label={playing ? "Pause" : "Play"}>
            {playing ? <Pause size={20} /> : <Play size={20} style={{ marginLeft: 2 }} />}
          </button>
          <div style={{ flex: 1 }}>
            <div
              style={styles.track}
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const pct = (e.clientX - rect.left) / rect.width;
                if (episodeMode) {
                  // One continuous track — clicking the bar is a real seek.
                  seekEpisode(Math.min(Math.max(pct, 0), 0.999));
                } else {
                  playSegment(Math.min(Math.floor(pct * transcript.length), transcript.length - 1));
                }
              }}
            >
              <div style={{ ...styles.trackFill, width: `${progress}%` }} />
              <div style={{ ...styles.trackThumb, left: `${progress}%` }} />
            </div>
            <div style={styles.timeRow}>
              <span>Segment {playingIdx + 1} / {transcript.length}</span>
              <span>AI audio{episodeMode ? " · full episode" : ""}</span>
            </div>
          </div>
        </div>
      )}

      <div className="transcript" style={styles.transcript}>
        <p style={styles.transcriptLabel}>Transcript</p>
        {transcript.map((seg, i) => {
          // AI audio (once generated) takes priority for the "now playing"
          // highlight; otherwise clicking a line jumps the free browser voice.
          const active = audioReady ? i === playingIdx : browserPlaying && i === browserIdx;
          const clickable = audioReady || speechSupported;
          return (
            <div
              key={i}
              className="segment"
              style={{
                opacity: clickable ? (active ? 1 : 0.45) : 1,
                cursor: clickable ? "pointer" : "default",
              }}
              onClick={() => (audioReady ? playSegment(i) : jumpBrowserVoice(i))}
            >
              <span style={styles.segTime}>{clickable ? `#${i + 1}` : seg.t}</span>
              <span style={{ ...styles.segWho, color: seg.who === hosts[0] ? moss : amber }}>
                {seg.who}
              </span>
              <span style={styles.segLine}><Markdown>{seg.line}</Markdown></span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TutorPanel({ documentContext, documentId, docFileName, fromHistory, authedFetch }) {
  const historyNotice =
    `I can show this document's summary, quiz and podcast, but its text wasn't saved ` +
    `(it was analyzed before text storage was added). ` +
    `Re-upload "${docFileName || "the PDF"}" and I can answer questions about it again.`;

  const greeting =
    fromHistory && !documentContext
      ? historyNotice
      : "Ask me anything about this document. I'll only answer from what you uploaded.";

  const [msgs, setMsgs] = useState([{ role: "tutor", text: greeting }]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  // Restore the saved conversation for this document on open, so the tutor
  // picks up where it left off last time. Only replaces the opening greeting
  // (msgs untouched once a conversation is already in progress).
  useEffect(() => {
    if (!documentId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch(`/api/documents/${documentId}/chat`);
        if (!res.ok) return;
        const data = await res.json().catch(() => null);
        const saved = (data && data.messages) || [];
        if (!cancelled && saved.length > 0) {
          setMsgs((m) => (m.length <= 1 ? [{ role: "tutor", text: greeting }, ...saved] : m));
        }
      } catch {
        // best-effort — no saved chat to restore
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  // Persist the conversation (without the opening greeting) so it survives a
  // reload. Storage only — best-effort, and never blocks the chat.
  const persistChat = (messages) => {
    if (!documentId) return;
    authedFetch(`/api/documents/${documentId}/chat`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: messages.slice(1) }),
    }).catch(() => {});
  };

  const send = async () => {
    if (!input.trim() || busy) return;
    const userText = input.trim();
    const history = msgs.slice(1).map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { role: "user", text: userText }]);
    setInput("");

    if (!documentContext) {
      // No document text retained: either sample mode (canned demo answer)
      // or reopened from history (be honest — don't fake an answer).
      setTimeout(() => {
        setMsgs((m) => [
          ...m,
          {
            role: "tutor",
            text: fromHistory
              ? historyNotice
              : "Based on your notes: spaced repetition works because each review happens just as you're about to forget, which forces effortful retrieval and strengthens the memory. (This is a demo response — upload your own PDF to chat with the real AI tutor.)",
          },
        ]);
      }, 700);
      return;
    }

    setBusy(true);
    try {
      const res = await authedFetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_context: documentContext,
          file_name: docFileName,
          question: userText,
          history,
        }),
      });
      const data = await res.json().catch(() => null);
      const answer = res.ok
        ? data.answer
        : data?.detail || `The tutor is unavailable right now (error ${res.status}).`;
      setMsgs((m) => {
        const updated = [...m, { role: "tutor", text: answer }];
        // Only persist real tutor answers, not transient service errors.
        if (res.ok) persistChat(updated);
        return updated;
      });
    } catch {
      setMsgs((m) => [
        ...m,
        { role: "tutor", text: "Could not reach the tutor service. Please try again in a moment." },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fade tutor-wrap" style={styles.tutorWrap}>
      <div style={styles.chatScroll} role="log" aria-live="polite" aria-label="Tutor conversation">
        {msgs.map((m, i) => (
          <div
            key={i}
            style={{
              ...styles.bubble,
              ...(m.role === "user" ? styles.bubbleUser : styles.bubbleTutor),
            }}
          >
            {m.role === "user" ? m.text : <Markdown>{m.text}</Markdown>}
          </div>
        ))}
        {busy && (
          <div style={{ ...styles.bubble, ...styles.bubbleTutor, opacity: 0.6 }}>Thinking…</div>
        )}
      </div>
      <div style={styles.inputRow}>
        <input
          style={styles.chatInput}
          placeholder="Ask about your document…"
          aria-label="Ask the tutor about your document"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button style={{ ...styles.sendBtn, opacity: busy ? 0.5 : 1 }} onClick={send} disabled={busy}>
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}

const ink = "#1c2522";
const paper = "#f6f4ee";
const moss = "#3f7d5e";
const mossDeep = "#2e5d45";
const amber = "#e6a23c";
const line = "#e2ded3";
// muted and amberText are darker than their "moss"/"amber" siblings on
// purpose: those two are reserved for icons, borders and large display type,
// while muted/amberText carry small body/label text and need the extra
// contrast to clear WCAG AA (4.5:1) at 11-14px sizes.
const muted = "#5a6560";
const amberText = "#8f5a0f";

// Shared shape for the small pill badges in the header (usage + trend) —
// defined outside `styles` since a property can't reference the `styles`
// object it's still being assigned to.
const pillBadge = {
  fontSize: 12,
  color: muted,
  background: "#fff",
  border: `1px solid ${line}`,
  borderRadius: 20,
  padding: "5px 12px",
  fontVariantNumeric: "tabular-nums",
  whiteSpace: "nowrap",
};

const styles = {
  app: {
    minHeight: "100svh",
    background: paper,
    color: ink,
    fontFamily: "'Source Sans 3', sans-serif",
    fontSize: 16,
    lineHeight: 1.6,
  },
  header: {
    width: "min(1200px, calc(100vw - 56px))",
    margin: "0 auto",
    padding: "20px 0",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  brand: { display: "flex", alignItems: "center", gap: 10 },
  brandName: { fontWeight: 700, fontSize: 19, letterSpacing: "-0.02em", fontFamily: "'Fraunces', Georgia, serif" },
  brandTagline: {
    fontSize: 13,
    color: muted,
    paddingLeft: 12,
    marginLeft: 2,
    borderLeft: `1px solid ${line}`,
  },
  resetBtn: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    background: "transparent",
    border: `1px solid ${line}`,
    borderRadius: 8,
    padding: "7px 12px",
    fontSize: 13,
    color: muted,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  uploadWrap: {
    width: "min(1120px, calc(100vw - 56px))",
    minHeight: "calc(100svh - 92px)",
    margin: "0 auto",
    padding: "clamp(36px, 6vw, 92px) 0 80px",
    textAlign: "center",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
  },
  eyebrow: {
    textTransform: "uppercase",
    letterSpacing: "0.16em",
    fontSize: 11.5,
    fontWeight: 600,
    color: mossDeep,
    margin: "0 0 18px",
  },
  h1: {
    fontFamily: "'Fraunces', Georgia, serif",
    fontSize: "clamp(38px, 4vw, 58px)",
    lineHeight: 1.05,
    fontWeight: 600,
    letterSpacing: "-0.03em",
    margin: "0 0 20px",
  },
  h1accent: { color: moss, fontStyle: "italic" },
  sub: {
    fontSize: "clamp(16px, 1.35vw, 20px)",
    lineHeight: 1.6,
    color: muted,
    maxWidth: 640,
    margin: "0 auto 38px",
  },
  loadingBox: { display: "grid", placeItems: "center", gap: 8 },
  loadingText: { margin: 0, fontWeight: 600, fontSize: 15 },
  loadingSub: { margin: 0, fontSize: 13, color: muted },
  uploadIcon: {
    width: 56,
    height: 56,
    borderRadius: 16,
    background: "#fff",
    border: `1px solid ${line}`,
    display: "grid",
    placeItems: "center",
    color: moss,
    marginBottom: 4,
  },
  dropTitle: { margin: 0, fontWeight: 600, fontSize: 17 },
  dropSub: { margin: 0, fontSize: 13.5, color: muted },
  dropLimit: { margin: "6px 0 0", fontSize: 12, color: muted, opacity: 0.75 },
  errorText: {
    marginTop: 18,
    marginBottom: 0,
    maxWidth: 640,
    fontSize: 14,
    lineHeight: 1.5,
    color: "#b03d2e",
    background: "#fdeeea",
    border: "1px solid #f2cfc5",
    borderRadius: 10,
    padding: "10px 16px",
  },
  bannerBar: {
    width: "min(1200px, calc(100vw - 56px))",
    margin: "0 auto 20px",
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "8px 14px",
    background: "#fbeede",
    border: `1px solid #f0d9b8`,
    borderRadius: 12,
    padding: "10px 16px",
  },
  bannerText: { flex: "1 1 240px", margin: 0, fontSize: 13.5, lineHeight: 1.5, color: amberText },
  bannerBtn: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    background: "#fff",
    border: `1.5px solid ${moss}`,
    color: mossDeep,
    borderRadius: 10,
    padding: "7px 13px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
    whiteSpace: "nowrap",
  },
  bannerClose: {
    display: "grid",
    placeItems: "center",
    background: "none",
    border: "none",
    color: amberText,
    cursor: "pointer",
    padding: 4,
    borderRadius: 6,
    flexShrink: 0,
  },
  modalOverlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(28, 37, 34, 0.45)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    zIndex: 200,
  },
  modalCard: {
    width: "min(440px, 100%)",
    maxHeight: "calc(100svh - 40px)",
    overflowY: "auto",
    background: "#fff",
    border: `1px solid ${line}`,
    borderRadius: 18,
    padding: "28px 26px",
  },
  modalClose: {
    display: "grid",
    placeItems: "center",
    background: "none",
    border: "none",
    color: muted,
    cursor: "pointer",
    padding: 4,
    borderRadius: 6,
    marginTop: -4,
    marginRight: -6,
    flexShrink: 0,
  },
  starRow: { display: "flex", gap: 4, marginBottom: 18 },
  starBtn: {
    display: "grid",
    placeItems: "center",
    background: "none",
    border: "none",
    padding: 4,
    cursor: "pointer",
  },
  feedbackLabel: { display: "block", fontSize: 13, fontWeight: 600, color: ink, marginBottom: 6 },
  feedbackTextarea: {
    display: "block",
    width: "100%",
    border: `1px solid ${line}`,
    borderRadius: 10,
    padding: "12px 14px",
    fontSize: 14.5,
    fontFamily: "inherit",
    resize: "vertical",
    marginBottom: 14,
  },
  authForm: {
    marginTop: 28,
    width: "min(360px, 100%)",
    display: "grid",
    gap: 10,
    background: "#fff",
    border: `1px solid ${line}`,
    borderRadius: 18,
    padding: "28px 24px",
    textAlign: "left",
  },
  authTitle: {
    fontFamily: "'Fraunces', Georgia, serif",
    fontSize: 20,
    fontWeight: 600,
    margin: "0 0 6px",
    textAlign: "center",
  },
  authSwitch: {
    marginTop: 4,
    background: "transparent",
    border: "none",
    color: muted,
    fontSize: 13,
    cursor: "pointer",
    fontFamily: "inherit",
    textAlign: "center",
  },
  googleBtn: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    width: "100%",
    background: "#fff",
    color: ink,
    border: `1px solid ${line}`,
    borderRadius: 10,
    padding: "11px 20px",
    fontSize: 14.5,
    fontWeight: 600,
    fontFamily: "inherit",
    cursor: "pointer",
  },
  authDivider: { display: "flex", alignItems: "center", gap: 10, margin: "2px 0" },
  authDividerLine: { flex: 1, height: 1, background: line },
  authDividerText: { fontSize: 12.5, color: muted },
  headerRight: { display: "flex", alignItems: "center", gap: 10 },
  usageBadge: { ...pillBadge },
  trendBadge: { ...pillBadge, alignItems: "center", gap: 5, fontWeight: 600 },
  sampleBtn: {
    marginTop: 22,
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    background: "transparent",
    border: "none",
    color: ink,
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
    fontFamily: "inherit",
    borderBottom: `1.5px solid ${amber}`,
    paddingBottom: 2,
  },
  historyBox: { marginTop: 40, width: "min(560px, 100%)", textAlign: "left" },
  historyLoading: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    color: muted,
    fontSize: 14,
    padding: "10px 2px",
  },
  historyHead: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  historyTitle: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    fontSize: 12,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.1em",
    color: muted,
  },
  historyClear: {
    background: "transparent",
    border: "none",
    color: muted,
    fontSize: 12.5,
    cursor: "pointer",
    fontFamily: "inherit",
    textDecoration: "underline",
    padding: 0,
  },
  // minmax(0, 1fr) pins items to the container width so long nowrap
  // titles ellipsize instead of stretching the track (matters in the
  // narrow sidebar; harmless inline).
  historyList: { display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 6 },
  historyItem: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    background: "#fff",
    border: `1px solid ${line}`,
    borderRadius: 12,
    padding: "10px 12px",
    cursor: "pointer",
    transition: "border-color .15s",
  },
  historyMeta: { flex: 1, minWidth: 0 },
  historyDocTitle: {
    margin: 0,
    fontSize: 13.5,
    fontWeight: 600,
    color: ink,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  historyFileName: {
    margin: 0,
    fontSize: 12,
    color: muted,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  historyDate: { fontSize: 11.5, color: muted, flexShrink: 0, fontVariantNumeric: "tabular-nums" },
  historyDelete: {
    background: "transparent",
    border: "none",
    color: muted,
    cursor: "pointer",
    padding: 7,
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderRadius: 6,
  },
  studyWrap: {
    width: "min(1200px, calc(100vw - 56px))",
    minHeight: "calc(100svh - 92px)",
    margin: "0 auto",
    padding: "clamp(16px, 3vw, 36px) 0 80px",
  },
  docHeader: { marginBottom: 24 },
  docChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    maxWidth: "100%",
    fontSize: 12.5,
    color: muted,
    background: "#fff",
    border: `1px solid ${line}`,
    borderRadius: 20,
    padding: "5px 12px",
    marginBottom: 14,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  docTitle: {
    fontFamily: "'Fraunces', Georgia, serif",
    fontSize: "clamp(30px, 3.6vw, 52px)",
    fontWeight: 600,
    letterSpacing: "-0.035em",
    margin: 0,
  },
  tabs: {
    display: "flex",
    justifyContent: "space-between",
    gap: 6,
    marginBottom: 22,
    borderBottom: `1px solid ${line}`,
    paddingBottom: 0,
    overflowX: "auto",
  },
  panel: {
    background: "#fff",
    border: `1px solid ${line}`,
    borderRadius: 18,
    padding: "clamp(24px, 3.2vw, 44px)",
    minHeight: "clamp(420px, 58svh, 680px)",
  },
  panelH: {
    fontFamily: "'Fraunces', Georgia, serif",
    fontSize: 20,
    fontWeight: 600,
    margin: "0 0 18px",
  },
  summaryList: { listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 16 },
  summaryItem: { display: "flex", gap: 14, fontSize: 15, lineHeight: 1.6, alignItems: "flex-start" },
  summaryNum: { color: moss, fontWeight: 700, fontSize: 13, fontVariantNumeric: "tabular-nums", marginTop: 2 },
  regenBox: { marginTop: 28, paddingTop: 20, borderTop: `1px solid ${line}` },
  regenSection: { marginBottom: 4 },
  regenHeading: { fontSize: 12.5, fontWeight: 700, color: muted, letterSpacing: 0.3, marginBottom: 10 },
  regenActions: { display: "flex", flexWrap: "wrap", gap: 8 },
  regenActionBtn: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    background: "#fff",
    border: `1.5px solid ${line}`,
    color: mossDeep,
    borderRadius: 10,
    padding: "9px 15px",
    fontSize: 13.5,
    fontWeight: 600,
    fontFamily: "inherit",
  },
  regenActionBtnCurrent: { background: "#eef4f0", borderColor: moss },
  regenCurrentTag: {
    fontSize: 10.5,
    fontWeight: 700,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    color: mossDeep,
    background: "#dcebe2",
    borderRadius: 5,
    padding: "1px 5px",
    marginLeft: 2,
  },
  regenStatus: { fontSize: 13, color: muted, margin: "12px 0 0" },
  focusBlock: { marginTop: 18 },
  focusLabel: { fontSize: 12.5, fontWeight: 700, color: muted, letterSpacing: 0.3, marginBottom: 8 },
  focusInputRow: { display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" },
  focusInput: {
    flex: "1 1 180px",
    minWidth: 140,
    border: `1px solid ${line}`,
    borderRadius: 10,
    padding: "9px 13px",
    fontSize: 13.5,
    fontFamily: "inherit",
    outline: "none",
    background: paper,
  },
  focusGenBtn: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    flexShrink: 0,
    background: moss,
    color: "#fff",
    border: "none",
    borderRadius: 10,
    padding: "9px 16px",
    fontSize: 13.5,
    fontWeight: 600,
    fontFamily: "inherit",
  },
  qBlock: { marginBottom: 24 },
  qText: { fontSize: 15.5, fontWeight: 500, lineHeight: 1.5, margin: "0 0 12px", display: "flex", gap: 10 },
  qIndex: { color: amberText, fontWeight: 700, fontSize: 13, marginTop: 2 },
  options: { display: "grid", gap: 8 },
  primaryBtn: {
    marginTop: 8,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    background: moss,
    color: "#fff",
    border: "none",
    borderRadius: 10,
    padding: "12px 20px",
    fontSize: 14.5,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  resultBox: { textAlign: "center", display: "grid", placeItems: "center", gap: 6, padding: "12px 0" },
  scoreRing: {
    width: 96,
    height: 96,
    borderRadius: "50%",
    border: `3px solid ${moss}`,
    display: "grid",
    placeItems: "center",
    marginBottom: 8,
  },
  scoreNum: { fontFamily: "'Fraunces', serif", fontSize: 34, fontWeight: 600, lineHeight: 1, color: mossDeep },
  scoreOf: { fontSize: 12, color: muted },
  resultSub: { fontSize: 14, color: muted, margin: "4px 0 8px" },
  weakRow: { display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", marginBottom: 14 },
  weakChip: {
    background: "#fbeede",
    color: amberText,
    border: "1px solid #f0d9b8",
    borderRadius: 20,
    padding: "5px 14px",
    fontSize: 13,
    fontWeight: 500,
  },
  quizActionRow: { display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "center", marginTop: 4 },
  quizHistory: { marginTop: 28, width: "100%", textAlign: "left" },
  quizHistoryTitle: { fontSize: 12.5, fontWeight: 700, color: muted, letterSpacing: 0.3, marginBottom: 8 },
  attemptRow: { borderTop: `1px solid ${line}`, padding: "8px 0" },
  attemptHeader: {
    display: "flex",
    justifyContent: "space-between",
    width: "100%",
    background: "none",
    border: "none",
    padding: 0,
    fontSize: 13.5,
    fontFamily: "inherit",
    color: ink,
    cursor: "pointer",
    fontVariantNumeric: "tabular-nums",
  },
  attemptDetail: { marginTop: 10, display: "grid", gap: 6 },
  attemptQ: { fontSize: 13, lineHeight: 1.5, margin: 0 },
  tutorWrap: { display: "flex", flexDirection: "column", minHeight: 420, height: "calc(58svh - 40px)" },
  chatScroll: { flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12, paddingRight: 4 },
  bubble: { maxWidth: "82%", padding: "11px 15px", borderRadius: 14, fontSize: 14.5, lineHeight: 1.5 },
  bubbleTutor: { background: paper, border: `1px solid ${line}`, alignSelf: "flex-start", borderBottomLeftRadius: 4 },
  bubbleUser: { background: moss, color: "#fff", alignSelf: "flex-end", borderBottomRightRadius: 4 },
  inputRow: { display: "flex", gap: 8, marginTop: 14 },
  chatInput: {
    flex: 1,
    minWidth: 0,
    border: `1px solid ${line}`,
    borderRadius: 10,
    padding: "12px 14px",
    fontSize: 14.5,
    fontFamily: "inherit",
    outline: "none",
    background: paper,
  },
  sendBtn: {
    background: moss,
    color: "#fff",
    border: "none",
    borderRadius: 10,
    width: 46,
    display: "grid",
    placeItems: "center",
    cursor: "pointer",
    flexShrink: 0,
  },
  podHero: { display: "flex", gap: 16, alignItems: "center", marginBottom: 24 },
  podCover: {
    width: 72,
    height: 72,
    borderRadius: 16,
    background: `linear-gradient(135deg, ${moss}, ${mossDeep})`,
    color: "#fff",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
  },
  podKicker: {
    textTransform: "uppercase",
    letterSpacing: "0.12em",
    fontSize: 11,
    fontWeight: 600,
    color: amberText,
    margin: "0 0 6px",
  },
  podTitle: {
    fontFamily: "'Fraunces', Georgia, serif",
    fontSize: 21,
    fontWeight: 600,
    margin: "0 0 4px",
    lineHeight: 1.15,
  },
  podHosts: { fontSize: 13.5, color: muted, margin: 0 },
  audioBar: { marginBottom: 16, minHeight: 34, display: "flex", alignItems: "center" },
  audioBtn: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    background: "#fff",
    border: `1.5px solid ${moss}`,
    color: mossDeep,
    borderRadius: 10,
    padding: "8px 16px",
    fontSize: 13.5,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  audioStatus: {
    display: "inline-flex",
    alignItems: "center",
    gap: 9,
    fontSize: 13.5,
    color: muted,
  },
  audioRetry: {
    background: "transparent",
    border: "none",
    color: mossDeep,
    fontWeight: 600,
    fontSize: 13.5,
    cursor: "pointer",
    fontFamily: "inherit",
    textDecoration: "underline",
    padding: 0,
  },
  player: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    background: paper,
    border: `1px solid ${line}`,
    borderRadius: 14,
    padding: "16px 18px",
    marginBottom: 26,
  },
  playBtn: {
    width: 48,
    height: 48,
    borderRadius: "50%",
    background: moss,
    color: "#fff",
    border: "none",
    display: "grid",
    placeItems: "center",
    cursor: "pointer",
    flexShrink: 0,
  },
  track: { position: "relative", height: 6, background: line, borderRadius: 3, cursor: "pointer" },
  trackFill: { position: "absolute", left: 0, top: 0, height: "100%", background: moss, borderRadius: 3 },
  trackThumb: {
    position: "absolute",
    top: "50%",
    width: 13,
    height: 13,
    background: "#fff",
    border: `2.5px solid ${moss}`,
    borderRadius: "50%",
    transform: "translate(-50%, -50%)",
  },
  timeRow: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: 12,
    color: muted,
    marginTop: 8,
    fontVariantNumeric: "tabular-nums",
  },
  freeTag: { color: mossDeep, fontWeight: 600 },
  transcript: { borderTop: `1px solid ${line}`, paddingTop: 18 },
  transcriptLabel: {
    textTransform: "uppercase",
    letterSpacing: "0.12em",
    fontSize: 11,
    fontWeight: 600,
    color: muted,
    margin: "0 0 14px",
  },
  segTime: {
    fontSize: 11.5,
    color: muted,
    fontVariantNumeric: "tabular-nums",
    width: 32,
    flexShrink: 0,
    marginTop: 2,
  },
  segWho: { fontSize: 13, fontWeight: 700, width: 44, flexShrink: 0, marginTop: 1 },
  segLine: { fontSize: 14.5, lineHeight: 1.55 },
};

const css = `
@import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..600;1,9..144,400..600&family=Source+Sans+3:wght@400;500;600;700&display=swap');

* { box-sizing: border-box; }
html, body, #root { min-height: 100%; }
body { margin: 0; overflow-x: hidden; }
button, input { -webkit-tap-highlight-color: transparent; }

.skip-link {
  position: absolute;
  top: -48px;
  left: 12px;
  z-index: 100;
  background: ${ink};
  color: #fff;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: top .15s;
}
.skip-link:focus { top: 12px; }

/* Fallback focus ring for every interactive control that doesn't already
   define its own :focus-visible treatment above/below. */
button:focus-visible,
a:focus-visible,
input:focus-visible,
textarea:focus-visible,
[role="button"]:focus-visible,
[tabindex]:focus-visible {
  outline: 3px solid ${amberText};
  outline-offset: 2px;
}

.app-shell {
  width: 100%;
  overflow-x: hidden;
}

.dropzone {
  width: min(760px, 100%);
  min-height: clamp(260px, 34vh, 420px);
  background: #fff;
  border: 2px dashed ${line};
  border-radius: 24px;
  padding: clamp(36px, 5vw, 72px) 24px;
  display: grid;
  place-items: center;
  gap: 10px;
  cursor: pointer;
  transition: border-color .2s, background .2s, transform .15s;
}
.dropzone:hover { border-color: ${moss}; transform: translateY(-2px); }
.dropzone.drag { border-color: ${moss}; background: #f0f5f1; }
.dropzone.loading { cursor: default; border-style: solid; }
.dropzone:focus-visible { outline: 3px solid ${amberText}; outline-offset: 3px; }

.spinner {
  width: 34px; height: 34px;
  border: 3px solid ${line};
  border-top-color: ${moss};
  border-radius: 50%;
  animation: spin .8s linear infinite;
}
.spinner-sm { width: 18px; height: 18px; border-width: 2.5px; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Recent documents: inline block below the dropzone on small screens, a
   Claude-style left sidebar on laptops and up. Same HistoryPanel markup is
   rendered in both containers; these rules decide which one is visible. */
.history-sidebar { display: none; }
.upload-main { display: contents; }
@media (min-width: 1100px) {
  .upload-wrap.has-sidebar {
    display: grid !important;
    grid-template-columns: 300px minmax(0, 1fr);
    column-gap: clamp(32px, 4vw, 64px);
    /* the inline flex style centers items; in grid mode the sidebar
       should stretch so its divider runs the full height */
    align-items: stretch !important;
    padding-top: 40px !important;
  }
  .upload-wrap.has-sidebar .history-sidebar {
    display: block;
    text-align: left;
    border-right: 1px solid ${line};
    padding-right: 28px;
  }
  .history-sidebar-body {
    position: sticky;
    top: 24px;
    max-height: calc(100svh - 48px);
    overflow-y: auto;
  }
  .upload-wrap.has-sidebar .upload-main {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .upload-wrap.has-sidebar .history-inline { display: none !important; }
}

.brand-tagline { display: none; }
@media (min-width: 640px) {
  .brand-tagline { display: inline; }
}

.trend-badge { display: none; }
@media (min-width: 760px) {
  .trend-badge { display: inline-flex; }
}

/* Usage badge ("N/limit today") updates live after every AI action; this
   flash is what makes the silent number change readable as an update
   rather than a layout glitch. Same notice tokens as the weak-topic chip
   and prototype banner, so "something changed" reads consistently. */
.usage-badge { transition: background-color .3s ease, border-color .3s ease, color .3s ease; }
.usage-badge-pulse {
  animation: usage-pulse .7s ease;
  background: #fbeede !important;
  border-color: #f0d9b8 !important;
  color: ${amberText} !important;
}
@keyframes usage-pulse {
  0% { transform: scale(1); }
  30% { transform: scale(1.12); }
  100% { transform: scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .usage-badge-pulse { animation: none; }
}

.tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: max-content;
  background: transparent;
  border: none;
  padding: 10px 16px 13px;
  margin-bottom: -1px;
  font-size: 14px;
  font-weight: 500;
  color: ${muted};
  cursor: pointer;
  font-family: inherit;
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
}
.tab:hover { color: ${ink}; }
.tab.active { color: ${mossDeep}; border-bottom-color: ${moss}; font-weight: 600; }

.opt {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  text-align: left;
  background: ${paper};
  border: 1.5px solid ${line};
  border-radius: 11px;
  padding: 13px 15px;
  font-size: 14.5px;
  color: ${ink};
  cursor: pointer;
  font-family: inherit;
  transition: border-color .15s, background .15s;
}
.opt:hover { border-color: ${moss}; }
.opt .optDot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid ${line};
  flex-shrink: 0;
  transition: all .15s;
}
.opt.picked { border-color: ${moss}; background: #f0f5f1; }
.opt.picked .optDot { border-color: ${moss}; background: ${moss}; outline: 3px solid #f0f5f1; outline-offset: -3px; }
.opt:focus-visible { outline: 3px solid ${amberText}; outline-offset: 2px; }

.segment {
  display: grid;
  grid-template-columns: 42px 54px 1fr;
  gap: 12px;
  padding: 9px 8px;
  border-radius: 9px;
  cursor: pointer;
  transition: opacity .25s, background .15s;
}
.segment:hover { background: ${paper}; }

.history-item:hover { border-color: ${moss}; }
.history-item button:hover { background: ${paper}; color: ${ink}; }

.google-btn:hover { border-color: ${moss}; background: ${paper}; }

.fade { animation: fade .35s ease; }
@keyframes fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

/* Flashcards — a physical index-card feel: a stacked deck behind the card,
   a true 3D flip on tap, moss front / amber back matching the app accents. */
.fc-scene {
  perspective: 1200px;
  height: clamp(220px, 32vh, 290px);
  margin: 18px 0 14px;
  position: relative;
}
/* the "rest of the deck" peeking out behind the top card */
.fc-scene::before, .fc-scene::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 18px;
  border: 1.5px solid ${line};
  background: #fff;
  z-index: 0;
}
.fc-scene::before { transform: rotate(-1.6deg) translateY(7px); }
.fc-scene::after { transform: rotate(1.1deg) translateY(4px); background: ${paper}; }
.fc-card {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
  font-family: inherit;
  transform-style: preserve-3d;
  transition: transform .55s cubic-bezier(.4, .2, .2, 1);
}
.fc-card.flipped { transform: rotateY(180deg); }
.fc-card:focus-visible { outline: none; }
.fc-card:focus-visible .fc-face { outline: 3px solid ${amberText}; outline-offset: 3px; }
.fc-face {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px 22px 34px;
  border-radius: 18px;
  border: 2px solid ${moss};
  background: #fff;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
  overflow-y: auto;
}
.fc-face.back {
  transform: rotateY(180deg);
  border-color: ${amberText};
  background: #fdf9f0;
}
.fc-kicker {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.4px;
  text-transform: uppercase;
  color: ${moss};
}
.fc-face.back .fc-kicker { color: ${amberText}; }
.fc-term {
  font-family: 'Fraunces', Georgia, serif;
  font-size: clamp(22px, 4.5vw, 30px);
  font-weight: 600;
  line-height: 1.25;
  color: ${ink};
  text-align: center;
}
.fc-answer {
  font-size: 15.5px;
  line-height: 1.65;
  color: ${ink};
  text-align: center;
  max-width: 52ch;
}
.fc-hint {
  position: absolute;
  bottom: 12px;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  font-size: 11.5px;
  color: ${muted};
}
.fc-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}
.fc-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1.5px solid ${line};
  background: #fff;
  color: ${mossDeep};
  cursor: pointer;
  font-family: inherit;
  transition: border-color .15s, background .15s, opacity .15s;
}
.fc-arrow:hover:not(:disabled) { border-color: ${moss}; background: #f0f5f1; }
.fc-arrow:disabled { opacity: .35; cursor: default; }
.fc-arrow:focus-visible { outline: 3px solid ${amberText}; outline-offset: 2px; }
.fc-dots { display: flex; align-items: center; gap: 7px; }
.fc-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: ${line};
  border: none;
  padding: 0;
  cursor: pointer;
  transition: background .2s, width .2s;
}
.fc-dot.active { width: 20px; background: ${moss}; }
.fc-dot:focus-visible { outline: 2px solid ${amberText}; outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) {
  .fc-card { transition: none; }
}

@media (min-width: 900px) {
  .panel .fade {
    max-width: 860px;
  }

  .study-wrap {
    display: grid !important;
    grid-template-columns: minmax(220px, 320px) minmax(0, 1fr);
    grid-template-rows: auto 1fr;
    column-gap: clamp(28px, 4vw, 56px);
    align-items: start;
  }

  .doc-header {
    grid-column: 1 / -1;
  }

  .tabs {
    grid-column: 1;
    grid-row: 2;
    display: grid !important;
    gap: 8px !important;
    border-bottom: 0 !important;
    overflow: visible !important;
    position: sticky;
    top: 20px;
  }

  .tab {
    width: 100%;
    justify-content: flex-start;
    border: 1px solid ${line};
    border-radius: 14px;
    margin-bottom: 0;
    padding: 14px 16px;
    background: #fff;
  }

  .tab.active {
    border-color: ${moss};
    border-bottom-color: ${moss};
    background: #f0f5f1;
  }

  .panel {
    grid-column: 2;
    grid-row: 2;
  }
}

@media (max-width: 700px) {
  .app-header {
    width: calc(100vw - 32px) !important;
    padding: 16px 0 !important;
  }

  .upload-wrap,
  .study-wrap {
    width: calc(100vw - 32px) !important;
    min-height: auto !important;
    padding-bottom: 40px !important;
  }

  .upload-wrap {
    justify-content: flex-start !important;
    padding-top: 42px !important;
  }

  .hero-title {
    font-size: clamp(36px, 11vw, 48px) !important;
    line-height: 1.05 !important;
  }

  .hero-title br {
    display: none;
  }

  .hero-sub {
    font-size: 15px !important;
    margin-bottom: 28px !important;
  }

  .dropzone {
    width: 100%;
    min-height: 220px;
    border-radius: 18px;
    padding: 34px 18px;
  }

  .doc-title {
    font-size: 30px !important;
  }

  .tabs {
    gap: 0 !important;
    margin-left: -16px !important;
    margin-right: -16px !important;
    padding-left: 16px !important;
    padding-right: 16px !important;
    scrollbar-width: none;
  }

  .tabs::-webkit-scrollbar {
    display: none;
  }

  .tab {
    gap: 4px;
    padding: 10px 7px 13px;
    font-size: 13px;
  }

  /* Larger tab icons (18px) fit fine at tablet/desktop widths but overflow
     the five-tab row here — back to the size the exact-fit mobile layout
     was tuned against. */
  .tab svg {
    width: 15px;
    height: 15px;
  }

  .panel {
    min-height: auto !important;
    padding: 20px 18px !important;
    border-radius: 16px !important;
  }

  .pod-hero,
  .player {
    align-items: flex-start !important;
  }

  .player {
    gap: 12px !important;
    padding: 14px !important;
  }

  .segment {
    grid-template-columns: 1fr;
    gap: 3px;
    padding: 10px 0;
  }

  .tutor-wrap {
    min-height: 420px !important;
    height: 60svh !important;
  }
}

@media (max-width: 420px) {
  .app-header {
    width: calc(100vw - 24px) !important;
  }

  .upload-wrap,
  .study-wrap {
    width: calc(100vw - 24px) !important;
  }

  .brandName {
    font-size: 16px;
  }

  .sampleBtn,
  .primaryBtn {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, .fade, .dropzone { animation: none !important; transition: none !important; }
}
`;
