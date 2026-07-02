import React, { useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  FileText,
  Headphones,
  ListChecks,
  MessageCircle,
  Pause,
  Play,
  RotateCcw,
  Send,
  Sparkles,
  Upload,
} from "lucide-react";

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

export default function StudyMVP() {
  const [stage, setStage] = useState("upload");
  const [tab, setTab] = useState("summary");
  const [fileName, setFileName] = useState("");
  const [loading, setLoading] = useState(false);
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState("");
  const fileRef = useRef(null);

  const startUpload = async (file) => {
    setError("");

    if (!file) {
      // Sample mode: show bundled demo content without hitting the backend.
      setFileName("psychology-ch6.pdf");
      setLoading(true);
      setTimeout(() => {
        setDoc({ ...MOCK, documentContext: null });
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
      const res = await fetch(`${API_BASE}/api/pdf/analyze`, {
        method: "POST",
        body: form,
      });
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
      });
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
        {stage === "study" && (
          <button style={styles.resetBtn} onClick={() => setStage("upload")}>
            <RotateCcw size={14} /> New upload
          </button>
        )}
      </header>

      {stage === "upload" ? (
        <UploadScreen loading={loading} onUpload={startUpload} fileRef={fileRef} error={error} />
      ) : (
        <StudyScreen tab={tab} setTab={setTab} fileName={fileName} doc={doc} />
      )}
    </div>
  );
}

function UploadScreen({ loading, onUpload, fileRef, error }) {
  const [drag, setDrag] = useState(false);

  return (
    <main className="upload-wrap" style={styles.uploadWrap}>
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
    </main>
  );
}

function StudyScreen({ tab, setTab, fileName, doc }) {
  return (
    <main className="study-wrap" style={styles.studyWrap}>
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
              <Icon size={15} strokeWidth={2.2} />
              {s.label}
            </button>
          );
        })}
      </nav>

      <section className="panel" style={styles.panel}>
        {tab === "summary" && <SummaryPanel doc={doc} />}
        {tab === "quiz" && <QuizPanel doc={doc} />}
        {tab === "podcast" && <PodcastPanel doc={doc} />}
        {tab === "tutor" && <TutorPanel documentContext={doc.documentContext} docFileName={doc.docFileName} />}
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
            <span>{point}</span>
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

function PodcastPanel({ doc }) {
  const { duration, hosts, transcript } = doc.podcast;
  const [playing, setPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef(null);

  const toSec = (mmss) => {
    const [m, s] = mmss.split(":").map(Number);
    return m * 60 + s;
  };

  const total = Math.max(toSec(duration) || 600, toSec(transcript[transcript.length - 1]?.t || "0:00") + 30);

  const fmt = (sec) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  const toggle = () => {
    if (playing) {
      clearInterval(intervalRef.current);
      setPlaying(false);
      return;
    }

    setPlaying(true);
    intervalRef.current = setInterval(() => {
      setElapsed((e) => {
        if (e >= total) {
          clearInterval(intervalRef.current);
          setPlaying(false);
          return total;
        }
        return e + 2;
      });
    }, 200);
  };

  const activeIdx = transcript.reduce((acc, seg, i) => (elapsed >= toSec(seg.t) ? i : acc), 0);
  const progress = Math.min((elapsed / total) * 100, 100);

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
              setElapsed(Math.round(pct * total));
            }}
          >
            <div style={{ ...styles.trackFill, width: `${progress}%` }} />
            <div style={{ ...styles.trackThumb, left: `${progress}%` }} />
          </div>
          <div style={styles.timeRow}>
            <span>{fmt(elapsed)}</span>
            <span>{duration}</span>
          </div>
        </div>
      </div>

      <div className="transcript" style={styles.transcript}>
        <p style={styles.transcriptLabel}>Transcript</p>
        {transcript.map((seg, i) => {
          const active = i === activeIdx;
          return (
            <div
              key={i}
              className="segment"
              style={{ opacity: active ? 1 : 0.45 }}
              onClick={() => setElapsed(toSec(seg.t))}
            >
              <span style={styles.segTime}>{seg.t}</span>
              <span style={{ ...styles.segWho, color: seg.who === hosts[0] ? moss : amber }}>
                {seg.who}
              </span>
              <span style={styles.segLine}>{seg.line}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TutorPanel({ documentContext, docFileName }) {
  const [msgs, setMsgs] = useState([
    {
      role: "tutor",
      text: "Ask me anything about this document. I'll only answer from what you uploaded.",
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
      // Sample mode: no uploaded document to ground answers in.
      setTimeout(() => {
        setMsgs((m) => [
          ...m,
          {
            role: "tutor",
            text:
              "Based on your notes: spaced repetition works because each review happens just as you're about to forget, which forces effortful retrieval and strengthens the memory. (This is a demo response — upload your own PDF to chat with the AI tutor.)",
          },
        ]);
      }, 700);
      return;
    }

    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
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
            {m.text}
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
