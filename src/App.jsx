import React, { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Clock,
  FileText,
  Headphones,
  ListChecks,
  LogOut,
  MessageCircle,
  Pause,
  Play,
  RotateCcw,
  Send,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { onAuthStateChanged, signInWithEmailAndPassword, signOut } from "firebase/auth";
import ReactMarkdown from "react-markdown";
import { auth } from "./firebase";

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
    default:
      return "Something went wrong. Please try again.";
  }
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

  return (
    <main className="upload-wrap" style={styles.uploadWrap}>
      <p style={styles.eyebrow}>Upload once · study every way</p>
      <h1 className="hero-title" style={styles.h1}>
        Turn any document into a<br />
        <span style={styles.h1accent}>study session.</span>
      </h1>
      <p className="hero-sub" style={styles.sub}>
        This app is invite-only. Sign in with your account to continue.
      </p>
      <form onSubmit={submit} style={styles.authForm}>
        <h2 style={styles.authTitle}>Sign in</h2>
        <input
          style={styles.chatInput}
          type="email"
          required
          placeholder="Email"
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
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {(error || blockedMessage) && <p style={styles.errorText}>{error || blockedMessage}</p>}
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
  const [profile, setProfile] = useState(null);
  const [blockedMessage, setBlockedMessage] = useState("");
  const fileRef = useRef(null);

  useEffect(() => onAuthStateChanged(auth, setUser), []);

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
    return res;
  };

  const refreshHistory = async () => {
    try {
      const res = await authedFetch("/api/documents");
      const data = await res.json().catch(() => null);
      if (res.ok) setHistory(data.documents);
    } catch {
      // best-effort — history list isn't critical path
    }
  };

  const refreshProfile = async () => {
    try {
      const res = await authedFetch("/api/profile");
      const data = await res.json().catch(() => null);
      if (res.ok) setProfile(data);
    } catch {
      // best-effort
    }
  };

  useEffect(() => {
    if (user) {
      setBlockedMessage("");
      refreshHistory();
      refreshProfile();
    } else {
      setHistory([]);
      setProfile(null);
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
    try {
      const res = await authedFetch(`/api/documents/${entry.id}`);
      const data = await res.json().catch(() => null);
      if (res.ok && data.document_context) context = data.document_context;
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

  if (user === undefined) {
    return (
      <div className="app-shell" style={styles.app}>
        <style>{css}</style>
        <main style={{ ...styles.uploadWrap, alignItems: "center", justifyContent: "center" }}>
          <div className="spinner" />
        </main>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="app-shell" style={styles.app}>
        <style>{css}</style>
        <header className="app-header" style={styles.header}>
          <div style={styles.brand}>
            <div style={styles.logoMark}>
              <BookOpen size={18} strokeWidth={2.4} />
            </div>
            <span style={styles.brandName}>Marrow</span>
          </div>
        </header>
        <AuthScreen blockedMessage={blockedMessage} />
      </div>
    );
  }

  return (
    <div className="app-shell" style={styles.app}>
      <style>{css}</style>
      <header className="app-header" style={styles.header}>
        <div style={styles.brand}>
          <div style={styles.logoMark}>
            <BookOpen size={18} strokeWidth={2.4} />
          </div>
          <span style={styles.brandName}>Marrow</span>
        </div>
        <div style={styles.headerRight}>
          {profile && (
            <span style={styles.usageBadge}>
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

      {stage === "upload" ? (
        <UploadScreen
          loading={loading}
          onUpload={startUpload}
          fileRef={fileRef}
          error={error}
          history={history}
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
          history={history}
          onOpenHistory={openHistoryEntry}
          onDeleteHistory={deleteHistoryEntry}
          onClearHistory={clearAllHistory}
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

function HistoryList({ history, onOpenHistory, onDeleteHistory, onClearHistory, activeId }) {
  return (
    <div className="history-box" style={styles.historyBox}>
      <div style={styles.historyHead}>
        <span style={styles.historyTitle}>
          <Clock size={13} /> Recent documents
        </span>
        <button style={styles.historyClear} onClick={onClearHistory}>
          Clear all
        </button>
      </div>
      <div style={styles.historyList}>
        {history.map((entry) => {
          const active = entry.id === activeId;
          return (
            <div
              key={entry.id}
              className="history-item"
              style={{ ...styles.historyItem, ...(active ? styles.historyItemActive : null) }}
              onClick={() => onOpenHistory(entry)}
            >
              <FileText size={15} style={{ color: active ? moss : muted, flexShrink: 0 }} />
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
          );
        })}
      </div>
    </div>
  );
}

function UploadScreen({ loading, onUpload, fileRef, error, history, onOpenHistory, onDeleteHistory, onClearHistory }) {
  const [drag, setDrag] = useState(false);
  const hasHistory = !loading && history.length > 0;

  return (
    <main className={`upload-wrap ${hasHistory ? "has-history" : ""}`} style={styles.uploadWrap}>
      {hasHistory && (
        <div className="upload-history-col">
          <HistoryList
            history={history}
            onOpenHistory={onOpenHistory}
            onDeleteHistory={onDeleteHistory}
            onClearHistory={onClearHistory}
          />
        </div>
      )}

      <div className="upload-hero-col">
        <p style={styles.eyebrow}>Upload once · study every way</p>
        <h1 className="hero-title" style={styles.h1}>
          Turn any document into a<br />
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
          role="button"
          tabIndex={0}
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
            <div style={styles.loadingBox}>
              <div className="spinner" />
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

        {!loading && error && <p style={styles.errorText}>{error}</p>}

        {!loading && (
          <button style={styles.sampleBtn} onClick={() => onUpload(null)}>
            <FileText size={14} /> Try it with a sample document
            <ArrowRight size={14} />
          </button>
        )}
      </div>
    </main>
  );
}

function StudyScreen({
  tab,
  setTab,
  fileName,
  doc,
  authedFetch,
  history,
  onOpenHistory,
  onDeleteHistory,
  onClearHistory,
}) {
  return (
    <main className="study-wrap" style={styles.studyWrap}>
      <div className="doc-header" style={styles.docHeader}>
        <div style={styles.docChip}>
          <FileText size={14} />
          {fileName}
        </div>
        <h2 className="doc-title" style={styles.docTitle}>{doc.title}</h2>
      </div>

      <div className="study-sidebar">
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
                <Icon size={15} strokeWidth={2.2} />
                {s.label}
              </button>
            );
          })}
        </nav>

        {history.length > 0 && (
          <div className="study-history-sidebar">
            <HistoryList
              history={history}
              onOpenHistory={onOpenHistory}
              onDeleteHistory={onDeleteHistory}
              onClearHistory={onClearHistory}
              activeId={doc.documentId}
            />
          </div>
        )}
      </div>

      <section className="panel" style={styles.panel}>
        {tab === "summary" && <SummaryPanel doc={doc} />}
        {tab === "quiz" && <QuizPanel doc={doc} />}
        {tab === "podcast" && <PodcastPanel doc={doc} documentId={doc.documentId} authedFetch={authedFetch} />}
        {tab === "tutor" && (
          <TutorPanel
            documentContext={doc.documentContext}
            docFileName={doc.docFileName}
            fromHistory={doc.fromHistory}
            authedFetch={authedFetch}
          />
        )}
      </section>
    </main>
  );
}

function SummaryPanel({ doc }) {
  return (
    <div className="fade">
      <h3 style={styles.panelH}>Key points</h3>
      <ul style={styles.summaryList}>
        {doc.summary.map((point, i) => (
          <li key={i} style={styles.summaryItem}>
            <span style={styles.summaryNum}>{String(i + 1).padStart(2, "0")}</span>
            <span><Markdown>{point}</Markdown></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function QuizPanel({ doc }) {
  const [answers, setAnswers] = useState({});
  const [submitted, setSubmitted] = useState(false);

  const quiz = doc.quiz;
  const score = quiz.reduce((n, q, i) => (answers[i] === q.answer ? n + 1 : n), 0);
  const weak = quiz.filter((q, i) => answers[i] !== q.answer).map((q) => q.topic);

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
        <button
          style={styles.primaryBtn}
          onClick={() => {
            setAnswers({});
            setSubmitted(false);
          }}
        >
          <RotateCcw size={15} /> Retake quiz
        </button>
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
        onClick={() => setSubmitted(true)}
      >
        Check answers <ArrowRight size={15} />
      </button>
    </div>
  );
}

function PodcastPanel({ doc, documentId, authedFetch }) {
  const { duration, hosts, transcript } = doc.podcast;

  // AI audio state: idle → generating → ready (or error). There is no
  // simulated/fake playback — the player only appears once real audio
  // exists, so the play button never implies audio that isn't there.
  const [audioState, setAudioState] = useState("idle");
  const [audioUrls, setAudioUrls] = useState([]);
  const [genProgress, setGenProgress] = useState(0);
  const [audioError, setAudioError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [playingIdx, setPlayingIdx] = useState(0);
  const [segProgress, setSegProgress] = useState(0);
  const audioRef = useRef(null);

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  const generateAudio = async () => {
    setAudioState("generating");
    setAudioError("");
    setGenProgress(0);
    try {
      const urls = new Array(transcript.length);
      let next = 0;
      let done = 0;
      // ElevenLabs free tier allows 2 concurrent requests.
      const worker = async () => {
        while (next < transcript.length) {
          const i = next++;
          const seg = transcript[i];
          const res = await authedFetch("/api/podcast/segment-audio", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              text: seg.line,
              speaker: seg.who === hosts[0] ? 0 : 1,
              // Lets the backend cache/reuse generated audio for this exact
              // document + segment instead of paying for it again next time.
              document_id: documentId || null,
              segment_index: i,
            }),
          });
          if (!res.ok) {
            const data = await res.json().catch(() => null);
            throw new Error(data?.detail || `The audio service returned an error (${res.status}).`);
          }
          const blob = await res.blob();
          urls[i] = URL.createObjectURL(blob);
          done += 1;
          setGenProgress(done);
        }
      };
      await Promise.all([worker(), worker()]);
      setAudioUrls(urls);
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

  const playSegment = (i, urls = audioUrls) => {
    if (!urls[i]) return;
    if (!audioRef.current) audioRef.current = new Audio();
    const a = audioRef.current;
    a.src = urls[i];
    a.ontimeupdate = () => setSegProgress(a.duration ? a.currentTime / a.duration : 0);
    a.onended = () => {
      if (i + 1 < urls.length) {
        playSegment(i + 1, urls);
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
  const progress = Math.min(((playingIdx + segProgress) / transcript.length) * 100, 100);

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

      <div style={styles.audioBar}>
        {audioState === "idle" && (
          <button style={styles.audioBtn} onClick={generateAudio}>
            <Sparkles size={15} /> Generate AI audio
          </button>
        )}
        {audioState === "generating" && (
          <span style={styles.audioStatus}>
            <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
            Generating audio… {genProgress}/{transcript.length}
          </span>
        )}
        {audioState === "error" && (
          <span style={{ ...styles.audioStatus, color: "#b03d2e" }}>
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
                playSegment(Math.min(Math.floor(pct * transcript.length), transcript.length - 1));
              }}
            >
              <div style={{ ...styles.trackFill, width: `${progress}%` }} />
              <div style={{ ...styles.trackThumb, left: `${progress}%` }} />
            </div>
            <div style={styles.timeRow}>
              <span>Segment {playingIdx + 1} / {transcript.length}</span>
              <span>AI audio</span>
            </div>
          </div>
        </div>
      )}

      <div className="transcript" style={styles.transcript}>
        <p style={styles.transcriptLabel}>Transcript</p>
        {transcript.map((seg, i) => {
          const active = audioReady && i === playingIdx;
          return (
            <div
              key={i}
              className="segment"
              style={{
                opacity: audioReady ? (active ? 1 : 0.45) : 1,
                cursor: audioReady ? "pointer" : "default",
              }}
              onClick={() => audioReady && playSegment(i)}
            >
              <span style={styles.segTime}>{audioReady ? `#${i + 1}` : seg.t}</span>
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

function TutorPanel({ documentContext, docFileName, fromHistory, authedFetch }) {
  const historyNotice =
    `I can show this document's summary, quiz and podcast, but its text wasn't saved ` +
    `(it was analyzed before text storage was added). ` +
    `Re-upload "${docFileName || "the PDF"}" and I can answer questions about it again.`;

  const [msgs, setMsgs] = useState([
    {
      role: "tutor",
      text:
        fromHistory && !documentContext
          ? historyNotice
          : "Ask me anything about this document. I'll only answer from what you uploaded.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

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
      setMsgs((m) => [...m, { role: "tutor", text: answer }]);
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
      <div style={styles.chatScroll}>
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
const muted = "#6f7a73";

const styles = {
  app: {
    minHeight: "100svh",
    background: paper,
    color: ink,
    fontFamily: "'Inter', system-ui, sans-serif",
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
  logoMark: {
    width: 32,
    height: 32,
    borderRadius: 9,
    background: moss,
    color: "#fff",
    display: "grid",
    placeItems: "center",
  },
  brandName: { fontWeight: 700, fontSize: 18, letterSpacing: "-0.02em" },
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
    color: moss,
    margin: "0 0 18px",
  },
  h1: {
    fontFamily: "'Fraunces', Georgia, serif",
    fontSize: "clamp(42px, 5vw, 78px)",
    lineHeight: 1.02,
    fontWeight: 600,
    letterSpacing: "-0.035em",
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
  headerRight: { display: "flex", alignItems: "center", gap: 10 },
  usageBadge: {
    fontSize: 12,
    color: muted,
    background: "#fff",
    border: `1px solid ${line}`,
    borderRadius: 20,
    padding: "5px 12px",
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
  },
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
  historyItemActive: { borderColor: moss, background: "#f0f5f1" },
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
  historyList: { display: "grid", gap: 6 },
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
    padding: 4,
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
  qBlock: { marginBottom: 24 },
  qText: { fontSize: 15.5, fontWeight: 500, lineHeight: 1.5, margin: "0 0 12px", display: "flex", gap: 10 },
  qIndex: { color: amber, fontWeight: 700, fontSize: 13, marginTop: 2 },
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
    color: "#a96a14",
    border: "1px solid #f0d9b8",
    borderRadius: 20,
    padding: "5px 14px",
    fontSize: 13,
    fontWeight: 500,
  },
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
    color: amber,
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
@import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..600;1,9..144,400..600&family=Inter:wght@400;500;600;700&display=swap');

* { box-sizing: border-box; }
html, body, #root { min-height: 100%; }
body { margin: 0; overflow-x: hidden; }
button, input { -webkit-tap-highlight-color: transparent; }

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
.dropzone:focus-visible { outline: 3px solid ${amber}; outline-offset: 3px; }

.spinner {
  width: 34px; height: 34px;
  border: 3px solid ${line};
  border-top-color: ${moss};
  border-radius: 50%;
  animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

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
.opt.picked .optDot { border-color: ${moss}; background: ${moss}; box-shadow: inset 0 0 0 3px #f0f5f1; }
.opt:focus-visible { outline: 3px solid ${amber}; outline-offset: 2px; }

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

.upload-hero-col {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.upload-history-col {
  width: 100%;
  display: flex;
  justify-content: center;
}
.study-history-sidebar { display: none; }

.fade { animation: fade .35s ease; }
@keyframes fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

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

  .study-sidebar {
    grid-column: 1;
    grid-row: 2;
    position: sticky;
    top: 20px;
    display: flex;
    flex-direction: column;
    gap: 24px;
    max-height: calc(100vh - 40px);
    overflow-y: auto;
  }

  .study-history-sidebar {
    display: block;
    border-top: 1px solid ${line};
    padding-top: 20px;
  }

  .tabs {
    display: grid !important;
    gap: 8px !important;
    border-bottom: 0 !important;
    overflow: visible !important;
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

  .upload-wrap.has-history {
    display: grid !important;
    grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
    column-gap: clamp(28px, 4vw, 56px);
    align-items: start !important;
    justify-content: initial !important;
    padding-top: clamp(36px, 6vw, 72px) !important;
  }

  .upload-wrap.has-history .upload-hero-col {
    grid-column: 2;
    grid-row: 1;
  }

  .upload-wrap.has-history .upload-history-col {
    grid-column: 1;
    grid-row: 1;
    display: block;
    width: auto;
    position: sticky;
    top: 20px;
  }

  .upload-wrap.has-history .history-box,
  .study-history-sidebar .history-box {
    width: 100% !important;
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
    gap: 4px !important;
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
    padding: 10px 14px 12px;
    font-size: 13.5px;
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
