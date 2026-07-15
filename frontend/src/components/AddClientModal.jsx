import { useState } from "react";
import Modal from "./Modal";
import { api } from "../api";
import { toast } from "../toast";

const looksLikeTimeout = (msg) => /fetch|timeout|timed out|504|network/i.test(msg || "");

const STEPS = ["Documents", "Identity", "Voice", "Details"];

const empty = {
  name: "", specialty: "", linkedinUrl: "", tone: "", voiceSamples: "", topics: "",
  viewpoints: "", audience: "", keyMessages: "", ctaRules: "", guardrails: "", personalStory: "",
};

export default function AddClientModal({ open, onClose, onCreated }) {
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState([]);
  const [pastedText, setPastedText] = useState("");
  const [dragging, setDragging] = useState(false);
  const [reading, setReading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [creators, setCreators] = useState([]);
  const [f, setF] = useState(empty);

  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const reset = () => { setStep(0); setFiles([]); setPastedText(""); setReading(false); setSaving(false); setError(null); setProgress(null); setCreators([]); setF(empty); };
  const close = () => { reset(); onClose(); };

  const addFiles = (list) => {
    const chosen = Array.from(list || []).filter((x) => /\.(pdf|docx|txt)$/i.test(x.name));
    if (chosen.length) setFiles((prev) => [...prev, ...chosen]);
  };
  const removeFile = (i) => setFiles((prev) => prev.filter((_, idx) => idx !== i));

  const extractAndContinue = async () => {
    setError(null);
    if (files.length === 0 && !pastedText.trim()) { setStep(1); return; } // fill manually
    // Validate up front so the operator gets a clear reason, not a vague failure.
    const ALLOWED = [".pdf", ".docx", ".txt"];
    const MAX_MB = 4; // Vercel rejects request bodies over ~4.5MB before they reach us
    for (const f of files) {
      const ext = (f.name.slice(f.name.lastIndexOf(".")) || "").toLowerCase();
      if (!ALLOWED.includes(ext)) {
        const msg = `"${f.name}" is not a supported type. Please upload PDF, DOCX, or TXT (a .doc or Google/Pages doc won't work — export it to PDF first).`;
        setError(msg); toast(msg); return;
      }
      if (f.size > MAX_MB * 1024 * 1024) {
        const msg = `"${f.name}" is ${(f.size / 1048576).toFixed(1)}MB. Each file must be under ${MAX_MB}MB — compress the PDF or split it, then upload again.`;
        setError(msg); toast(msg); return;
      }
    }
    setReading(true);
    try {
      // Read each file's text one at a time (keeps each request small), then
      // extract from the combined text. Pasted text is included as-is.
      let combined = pastedText.trim() ? pastedText.trim() + "\n\n---\n\n" : "";
      const unreadable = [];
      for (let i = 0; i < files.length; i++) {
        setProgress(`Reading ${files[i].name} (${i + 1}/${files.length})…`);
        const r = await api.docText(files[i]);
        if (r.text && r.text.trim()) combined += r.text + "\n\n---\n\n";
        else unreadable.push(files[i].name);
      }
      if (!combined.trim()) {
        throw new Error(
          `No readable text found in ${unreadable.join(", ") || "those files"}. ` +
          `If it's a scanned or image-only PDF, upload a text-based version.`
        );
      }
      setProgress("Extracting the details…");
      const p = await api.extractBrand(combined);
      setF({
        name: p.name || "", specialty: p.specialty || "",
        linkedinUrl: "", tone: p.voice_guide || "", voiceSamples: p.voice_samples || "",
        topics: Array.isArray(p.topics) ? p.topics.join(", ") : "",
        viewpoints: p.viewpoints || "", audience: p.audience || "",
        keyMessages: p.key_messages || "", ctaRules: p.cta_rules || "", guardrails: p.guardrails || "",
        personalStory: p.personal_story || "",
      });
      setCreators(Array.isArray(p.suggested_creators) ? p.suggested_creators : []);
      setStep(1);
    } catch (err) {
      const msg = looksLikeTimeout(err.message)
        ? "That took too long to read. Try again, or upload fewer / smaller documents."
        : `Couldn't read those documents: ${err.message}`;
      setError(msg);
      toast(msg);
    } finally {
      setReading(false);
      setProgress(null);
    }
  };

  const next = () => {
    setError(null);
    if (step === 1 && (!f.name.trim() || !f.specialty.trim())) { setError("Name and specialty are required."); return; }
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };
  const back = () => { setError(null); setStep((s) => Math.max(s - 1, 0)); };

  const create = async () => {
    setSaving(true);
    setError(null);
    try {
      setProgress("Creating client…");
      const client = await api.createClient({
        name: f.name.trim(), specialty: f.specialty.trim(),
        linkedin_url: f.linkedinUrl.trim() || null,
        topics: f.topics.split(",").map((t) => t.trim()).filter(Boolean),
        tone_profile: f.tone.trim(), voice_guide: f.tone.trim(), voice_samples: f.voiceSamples,
        viewpoints: f.viewpoints, audience: f.audience,
        key_messages: f.keyMessages, cta_rules: f.ctaRules, guardrails: f.guardrails,
        personal_story: f.personalStory,
      });
      if (files.length) {
        setProgress("Saving documents…");
        for (const file of files) { try { await api.uploadDocument(client.id, file); } catch { /* keep going */ } }
      }
      if (creators.length) {
        setProgress("Finding people to track…");
        try { await api.trackSuggestedCreators(client.id, creators.map((c) => ({ name: c.name, reason: c.reason || "", profile_url: c.profile_url || "" }))); } catch { /* non-fatal */ }
      }
      reset();
      onCreated(client);
    } catch (err) {
      const msg = looksLikeTimeout(err.message) ? "That took too long. Please try again." : `Couldn't create the client: ${err.message}`;
      setError(msg);
      toast(msg);
      setSaving(false);
      setProgress(null);
    }
  };

  return (
    <Modal open={open} onClose={close} title="Add a client" width={560}>
      <Stepper step={step} />

      {step === 0 && (
        <div>
          <StepHead title="Upload their strategy docs" sub="Drop in the client's brand or strategy documents and we'll fill everything in for you. You can add more than one." />
          <div
            className={`dropzone${dragging ? " drag" : ""}`}
            onClick={() => document.getElementById("wiz-file").click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
          >
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Drop files here, or click to choose</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>PDF, Word, or text</div>
            <input id="wiz-file" type="file" accept=".pdf,.docx,.txt" multiple style={{ display: "none" }} onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          </div>

          {files.length > 0 && (
            <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
              {files.map((file, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 10, background: "var(--bg)" }}>
                  <span style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>📄 {file.name}</span>
                  <button className="btn btn-ghost" style={{ padding: "3px 9px", fontSize: 12 }} onClick={() => removeFile(i)}>Remove</button>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 18 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>
              Or paste the strategy / brand doc text here — handy if a file won't upload (a Google/Word doc, a large or scanned PDF).
            </div>
            <textarea
              value={pastedText}
              onChange={(e) => setPastedText(e.target.value)}
              rows={5}
              placeholder="Paste the client's strategy or brand document text…"
              style={{ width: "100%", boxSizing: "border-box", border: "1px solid var(--border)", borderRadius: 10, padding: 10, fontSize: 13, lineHeight: 1.5, fontFamily: "inherit", resize: "vertical" }}
            />
          </div>

          {error && <ErrorLine text={error} />}

          <Footer
            right={
              <button className="btn btn-primary" onClick={extractAndContinue} disabled={reading}>
                {reading ? <><span className="spin" /> &nbsp;{progress || "Reading…"}</> : (files.length || pastedText.trim()) ? "Extract & continue" : "Continue"}
              </button>
            }
            leftText={(files.length || pastedText.trim()) ? null : "No docs? You can fill it in by hand."}
          />
        </div>
      )}

      {step === 1 && (
        <div>
          <StepHead title="Who is the client?" sub="Prefilled from your documents, edit anything." />
          <Field label="Name" value={f.name} onChange={(v) => set("name", v)} placeholder="Dr. Jane Smith" />
          <Field label="Specialty" value={f.specialty} onChange={(v) => set("specialty", v)} placeholder="Cardiology" />
          <Field label="LinkedIn profile" hint="Optional" value={f.linkedinUrl} onChange={(v) => set("linkedinUrl", v)} placeholder="https://www.linkedin.com/in/..." />
          {error && <ErrorLine text={error} />}
          <Footer left={<button className="btn btn-ghost" onClick={back}>Back</button>} right={<button className="btn btn-primary" onClick={next}>Continue</button>} />
        </div>
      )}

      {step === 2 && (
        <div>
          <StepHead title="Their voice" sub="How they write, tone, phrasing, do's and don'ts. This shapes every drafted reply." />
          <Field textarea rows={7} label="Voice & tone" value={f.tone} onChange={(v) => set("tone", v)} placeholder="Direct, warm, cites specific evidence…" />
          <Field label="Topics" hint="Comma-separated, what they care about" value={f.topics} onChange={(v) => set("topics", v)} placeholder="heart failure, statins, cardiac imaging" />
          {error && <ErrorLine text={error} />}
          <Footer left={<button className="btn btn-ghost" onClick={back}>Back</button>} right={<button className="btn btn-primary" onClick={next}>Continue</button>} />
        </div>
      )}

      {step === 3 && (
        <div>
          <StepHead title="What they stand for" sub="The substance behind their replies, all editable, all extracted from the docs." />
          <Field textarea label="Viewpoints & opinions" value={f.viewpoints} onChange={(v) => set("viewpoints", v)} placeholder="The positions they actually hold…" />
          <Field textarea label="Audience" value={f.audience} onChange={(v) => set("audience", v)} placeholder="Who they're speaking to, and their pain points…" />
          <Field textarea label="Key messages" value={f.keyMessages} onChange={(v) => set("keyMessages", v)} placeholder="Core points they want to reinforce…" />
          <Field textarea label="Guardrails" hint="Hard rules the drafter must never break" value={f.guardrails} onChange={(v) => set("guardrails", v)} placeholder="e.g. never make claims without evidence…" />
          <Field textarea label="Personal story / why" hint="Their mission and personal anecdotes — used for genuine human touch" value={f.personalStory} onChange={(v) => set("personalStory", v)} placeholder="e.g. what drew them to this field, stories they tell…" />
          {creators.length > 0 && (
            <div className="field">
              <label className="field-label">People we'll track for them</label>
              <div className="field-hint">Found in the docs, we'll verify and start tracking the right profiles automatically. Review them under "Manage" afterwards.</div>
              <div style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
                {creators.map((c, i) => (
                  <div key={i} style={{ padding: "9px 12px", borderTop: i ? "1px solid var(--border)" : "none" }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{c.name}</div>
                    {c.reason && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>{c.reason}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {error && <ErrorLine text={error} />}
          <Footer
            left={<button className="btn btn-ghost" onClick={back} disabled={saving}>Back</button>}
            right={<button className="btn btn-primary" onClick={create} disabled={saving}>{saving ? <><span className="spin" /> &nbsp;{progress || "Creating…"}</> : "Create client"}</button>}
          />
        </div>
      )}
    </Modal>
  );
}

function Stepper({ step }) {
  return (
    <div className="stepper">
      {STEPS.map((label, i) => (
        <div key={label} style={{ display: "flex", alignItems: "center", flex: i < STEPS.length - 1 ? 1 : "0 0 auto" }}>
          <div className="step-node">
            <div className={`step-dot${i === step ? " active" : i < step ? " done" : ""}`}>{i < step ? "✓" : i + 1}</div>
            <span className={`step-label${i === step ? " active" : ""}`}>{label}</span>
          </div>
          {i < STEPS.length - 1 && <div className={`step-bar${i < step ? " done" : ""}`} />}
        </div>
      ))}
    </div>
  );
}

function StepHead({ title, sub }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontSize: 17, fontWeight: 700 }}>{title}</div>
      {sub && <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.5 }}>{sub}</div>}
    </div>
  );
}

function Field({ label, hint, value, onChange, placeholder, textarea, rows }) {
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      {hint && <div className="field-hint">{hint}</div>}
      {textarea ? (
        <textarea className="field-textarea" rows={rows || 4} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      ) : (
        <input className="field-input" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      )}
    </div>
  );
}

function ErrorLine({ text }) {
  return <div style={{ fontSize: 13, color: "var(--danger)", background: "var(--danger-bg)", padding: "8px 12px", borderRadius: 8, marginBottom: 12 }}>{text}</div>;
}

function Footer({ left, right, leftText }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 22 }}>
      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{left || leftText || <span />}</div>
      <div>{right}</div>
    </div>
  );
}
