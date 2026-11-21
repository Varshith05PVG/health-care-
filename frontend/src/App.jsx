import { useEffect, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  askRecordAssistant,
  clearSession,
  createHealthRecord,
  fetchHealthRecords,
  fetchPatient,
  fetchPatientQr,
  getSession,
  loginPatient,
  enrollFace,
  verifyFace,
  lookupScannedHealthId,
  requestPasswordReset,
  registerPatient,
  resetPatientPassword,
  saveSession,
  transcribeSpeech,
} from "./api/patients.js";
import { decodeHealthIdQr } from "./utils/healthIdQr.js";
import VoiceInterpreterPage from "./VoiceInterpreterPage.jsx";

const emptyRegistration = {
  name: "",
  age: "",
  gender: "",
  blood_group: "",
  language: "",
  phone: "",
  password: "",
};

const appTranslations = {
  en: {
    dashboard: "Dashboard", records: "Health records", scan: "Scan Health ID", assistant: "Record assistant",
    interpreter: "Voice interpreter", signOut: "Sign out", register: "Register", login: "Patient login",
    language: "Language", welcome: "Welcome back", loginHint: "Sign in with your phone number or Health ID and password.",
    identifier: "Phone number or Health ID", password: "Password", signIn: "Sign in", signingIn: "Signing in…",
    addRecord: "Add a health record", yourRecords: "Your records", recordType: "Record type", title: "Title",
    details: "Details", doctorName: "Doctor name", doctorSpecialization: "Doctor specialization",
    recordedOn: "Recorded on", saveRecord: "Save health record", savingRecord: "Saving record…",
    recordAdded: "Health record added.", noRecords: "No health records yet. Add a record to get started.",
  },
  hi: {
    dashboard: "डैशबोर्ड", records: "स्वास्थ्य रिकॉर्ड", scan: "हेल्थ आईडी स्कैन करें", assistant: "रिकॉर्ड सहायक",
    interpreter: "वॉइस इंटरप्रेटर", signOut: "साइन आउट", register: "पंजीकरण", login: "मरीज़ लॉगिन",
    language: "भाषा", welcome: "वापसी पर स्वागत है", loginHint: "फ़ोन नंबर या हेल्थ आईडी और पासवर्ड से साइन इन करें।",
    identifier: "फ़ोन नंबर या हेल्थ आईडी", password: "पासवर्ड", signIn: "साइन इन", signingIn: "साइन इन हो रहा है…",
    addRecord: "स्वास्थ्य रिकॉर्ड जोड़ें", yourRecords: "आपके रिकॉर्ड", recordType: "रिकॉर्ड प्रकार", title: "शीर्षक",
    details: "विवरण", doctorName: "डॉक्टर का नाम", doctorSpecialization: "डॉक्टर की विशेषज्ञता",
    recordedOn: "रिकॉर्ड की तारीख", saveRecord: "स्वास्थ्य रिकॉर्ड सेव करें", savingRecord: "रिकॉर्ड सेव हो रहा है…",
    recordAdded: "स्वास्थ्य रिकॉर्ड जोड़ दिया गया।", noRecords: "अभी कोई स्वास्थ्य रिकॉर्ड नहीं है।",
  },
  te: {
    dashboard: "డాష్‌బోర్డ్", records: "ఆరోగ్య రికార్డులు", scan: "హెల్త్ ID స్కాన్", assistant: "రికార్డ్ సహాయకుడు",
    interpreter: "వాయిస్ ఇంటర్‌ప్రెటర్", signOut: "సైన్ అవుట్", register: "నమోదు", login: "రోగి లాగిన్",
    language: "భాష", welcome: "తిరిగి స్వాగతం", loginHint: "ఫోన్ నంబర్ లేదా హెల్త్ ID మరియు పాస్‌వర్డ్‌తో సైన్ ఇన్ చేయండి.",
    identifier: "ఫోన్ నంబర్ లేదా హెల్త్ ID", password: "పాస్‌వర్డ్", signIn: "సైన్ ఇన్", signingIn: "సైన్ ఇన్ అవుతోంది…",
    addRecord: "ఆరోగ్య రికార్డ్ జోడించండి", yourRecords: "మీ రికార్డులు", recordType: "రికార్డ్ రకం", title: "శీర్షిక",
    details: "వివరాలు", doctorName: "డాక్టర్ పేరు", doctorSpecialization: "డాక్టర్ నైపుణ్యం",
    recordedOn: "రికార్డ్ తేదీ", saveRecord: "ఆరోగ్య రికార్డ్ సేవ్ చేయండి", savingRecord: "రికార్డ్ సేవ్ అవుతోంది…",
    recordAdded: "ఆరోగ్య రికార్డ్ జోడించబడింది.", noRecords: "ఇంకా ఆరోగ్య రికార్డులు లేవు.",
  },
};

function useAppLanguage() {
  const [language, setLanguage] = useState(() => localStorage.getItem("app-language") || "en");
  useEffect(() => {
    const update = () => setLanguage(localStorage.getItem("app-language") || "en");
    window.addEventListener("app-language-change", update);
    return () => window.removeEventListener("app-language-change", update);
  }, []);
  return [language, appTranslations[language] || appTranslations.en];
}

function LanguageSelector() {
  const [language] = useAppLanguage();
  function change(event) {
    localStorage.setItem("app-language", event.target.value);
    window.dispatchEvent(new Event("app-language-change"));
  }
  return <label className="language-selector"><span className="sr-only">Language</span><select aria-label="Language" value={language} onChange={change}><option value="en">English</option><option value="hi">हिन्दी</option><option value="te">తెలుగు</option></select></label>;
}

function ProtectedPage({ children }) {
  return getSession()?.access_token ? children : <Navigate to="/login" replace />;
}

function FaceCameraDialog({ mode, onSuccess, onCancel }) {
  const videoRef = useRef(null);
  const faceApiRef = useRef(null);
  const [stream, setStream] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream;
      videoRef.current.play().catch((playError) => setMessage(playError.message));
    }
  }, [stream]);
  useEffect(() => () => stream?.getTracks().forEach((track) => track.stop()), [stream]);

  async function startCamera() {
    setMessage("");
    setBusy(true);
    try {
      const faceapi = await import("@vladmandic/face-api");
      faceApiRef.current = faceapi;
      await Promise.all([
        faceapi.nets.tinyFaceDetector.loadFromUri("/models"),
        faceapi.nets.faceLandmark68TinyNet.loadFromUri("/models"),
        faceapi.nets.faceRecognitionNet.loadFromUri("/models"),
      ]);
      const cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } });
      setStream(cameraStream);
    } catch (cameraError) {
      setMessage(cameraError?.name === "NotAllowedError" ? "Allow camera access to continue." : cameraError.message);
    } finally {
      setBusy(false);
    }
  }

  async function scanFace() {
    if (!videoRef.current) return;
    setBusy(true);
    setMessage("");
    try {
      const faceapi = faceApiRef.current;
      if (!faceapi) throw new Error("Start the camera before scanning your face.");
      const result = await faceapi.detectSingleFace(
        videoRef.current,
        new faceapi.TinyFaceDetectorOptions({ inputSize: 416, scoreThreshold: 0.6 }),
      ).withFaceLandmarks(true).withFaceDescriptor();
      if (!result) {
        setMessage("No clear face detected. Center your face and try again.");
        return;
      }
      await onSuccess(Array.from(result.descriptor));
    } catch (scanError) {
      setMessage(scanError.message || "Face verification failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="face-check" aria-label="Camera face verification">
      <h2>{mode === "enroll" ? "Set up camera face check" : "Verify your face"}</h2>
      <p className="muted">{mode === "enroll" ? "A face descriptor will be stored for future login checks. A photo is not stored." : "Look at the camera to verify your identity."}</p>
      {!stream ? <button type="button" onClick={startCamera} disabled={busy}>{busy ? "Starting camera…" : "Start camera"}</button> : (
        <>
          <video ref={videoRef} className="face-camera" autoPlay muted playsInline />
          <button type="button" onClick={scanFace} disabled={busy}>{busy ? "Checking…" : "Scan face"}</button>
        </>
      )}
      {message && <p className="notice error" role="alert">{message}</p>}
      <button type="button" className="text-button" onClick={onCancel} disabled={busy}>Cancel</button>
    </section>
  );
}

function SiteHeader() {
  const navigate = useNavigate();
  const session = getSession();
  const [, t] = useAppLanguage();
  return (
    <header className="site-header">
      <Link className="brand" to={session ? "/dashboard" : "/"} aria-label="Digital Health Record home">
        <span className="brand-mark" aria-hidden="true">+</span>
        <span>Care<span className="brand-light">Record</span></span>
      </Link>
      <nav aria-label="Main navigation">
        {session ? (
          <>
            <Link to="/dashboard">{t.dashboard}</Link>
            <Link to="/records">{t.records}</Link>
            <Link to="/scan">{t.scan}</Link>
            <Link to="/assistant">{t.assistant}</Link>
            <Link to="/interpreter">{t.interpreter}</Link>
            <button
              className="nav-button"
              onClick={() => {
                clearSession();
                navigate("/login");
              }}
            >
              {t.signOut}
            </button>
            <LanguageSelector />
          </>
        ) : (
          <>
            <Link to="/">{t.register}</Link>
            <Link className="nav-login" to="/login">{t.login}</Link>
            <Link to="/scan">{t.scan}</Link>
            <LanguageSelector />
          </>
        )}
      </nav>
    </header>
  );
}

function AppShell({ children }) {
  return (
    <>
      <SiteHeader />
      {children}
      <footer className="site-footer">Private patient record assistance · Not a substitute for professional medical advice</footer>
    </>
  );
}

function RegistrationPage() {
  const [form, setForm] = useState(emptyRegistration);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [faceFlow, setFaceFlow] = useState(null);
  const navigate = useNavigate();

  function updateField(event) {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const session = await registerPatient({ ...form, age: Number(form.age) });
      saveSession(session);
      setFaceFlow({ mode: "enroll", session });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function completeFace(descriptor) {
    await enrollFace(descriptor);
    setFaceFlow(null);
    navigate("/dashboard");
  }

  return (
    <AppShell>
      <main className="layout">
        <section className="intro">
          <p className="eyebrow">Your care, organized</p>
          <h1>One secure place for your health record.</h1>
          <p className="muted">Create your patient account to keep your Health ID and health records together.</p>
        </section>
        <section className="panel">
          <h2>Patient registration</h2>
          {faceFlow && <FaceCameraDialog mode={faceFlow.mode} onSuccess={completeFace} onCancel={() => { clearSession(); setFaceFlow(null); }} />}
          <form onSubmit={submit}>
            <label>Full name<input name="name" value={form.name} onChange={updateField} maxLength="120" autoComplete="name" required /></label>
            <div className="form-row">
              <label>Age<input name="age" type="number" min="0" max="125" value={form.age} onChange={updateField} required /></label>
              <label>Gender<input name="gender" value={form.gender} onChange={updateField} maxLength="40" required /></label>
            </div>
            <div className="form-row">
              <label>Blood group<input name="blood_group" value={form.blood_group} onChange={updateField} maxLength="10" placeholder="e.g. O+" required /></label>
              <label>Preferred language<input name="language" value={form.language} onChange={updateField} maxLength="60" required /></label>
            </div>
            <label>Phone number<input name="phone" type="tel" value={form.phone} onChange={updateField} placeholder="+919876543210" autoComplete="tel" required /></label>
            <label>Password<input name="password" type="password" value={form.password} onChange={updateField} minLength="12" maxLength="128" autoComplete="new-password" required /><span className="field-hint">Use at least 12 characters. Your password is stored as a secure hash.</span></label>
            {error && <p className="notice error" role="alert">{error}</p>}
            <button type="submit" disabled={submitting}>{submitting ? "Creating account…" : "Create patient account"}</button>
          </form>
          <p className="form-note">Already registered? <Link to="/login">Sign in</Link></p>
        </section>
      </main>
    </AppShell>
  );
}

function LoginPage() {
  const [, t] = useAppLanguage();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [resetError, setResetError] = useState("");
  const [resetMessage, setResetMessage] = useState("");
  const [resetIdentifier, setResetIdentifier] = useState("");
  const [resetOtp, setResetOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [resetOpen, setResetOpen] = useState(false);
  const [otpRequested, setOtpRequested] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [faceFlow, setFaceFlow] = useState(null);
  const navigate = useNavigate();

  async function submit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      clearSession();
      const session = await loginPatient({ identifier, password });
      if (session.face_required) {
        setFaceFlow({ mode: "verify", session });
      } else {
        saveSession(session);
        setFaceFlow({ mode: "enroll", session });
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function completeFace(descriptor) {
    if (faceFlow.mode === "verify") {
      const verifiedSession = await verifyFace(faceFlow.session.access_token, descriptor);
      saveSession(verifiedSession);
    } else {
      await enrollFace(descriptor);
    }
    setFaceFlow(null);
    navigate("/dashboard");
  }

  async function requestReset(event) {
    event.preventDefault();
    setResetError("");
    setResetMessage("");
    setSubmitting(true);
    try {
      const response = await requestPasswordReset(resetIdentifier);
      setResetMessage(response.message);
      setOtpRequested(true);
    } catch (requestError) {
      setResetError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmReset(event) {
    event.preventDefault();
    setResetError("");
    setResetMessage("");
    setSubmitting(true);
    try {
      const response = await resetPatientPassword({
        identifier: resetIdentifier,
        otp: resetOtp,
        new_password: newPassword,
      });
      setResetMessage(response.message);
      setOtpRequested(false);
      setResetOpen(false);
      setIdentifier(resetIdentifier);
      setPassword("");
      setResetOtp("");
      setNewPassword("");
    } catch (requestError) {
      setResetError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <main className="narrow-layout">
        <section className="panel">
          <p className="eyebrow">Patient access</p>
          <h1>{t.welcome}</h1>
          <p className="muted">{t.loginHint}</p>
          {faceFlow && <FaceCameraDialog mode={faceFlow.mode} onSuccess={completeFace} onCancel={() => { clearSession(); setFaceFlow(null); }} />}
          <form onSubmit={submit}>
            <label>{t.identifier}<input value={identifier} onChange={(event) => setIdentifier(event.target.value)} autoComplete="username" required /></label>
            <label>{t.password}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
            {error && <p className="notice error" role="alert">{error}</p>}
            <button type="submit" disabled={submitting}>{submitting ? t.signingIn : t.signIn}</button>
          </form>
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setResetOpen((open) => !open);
              setResetIdentifier(identifier);
              setResetError("");
              setResetMessage("");
              setOtpRequested(false);
            }}
          >
            Forgot Password?
          </button>
          {resetOpen && (
            <section className="password-reset" aria-label="Password reset">
              <h2>Reset your password</h2>
              {!otpRequested ? (
                <form onSubmit={requestReset}>
                  <label>Phone number or Health ID<input value={resetIdentifier} onChange={(event) => setResetIdentifier(event.target.value)} autoComplete="username" required /></label>
                  <button type="submit" disabled={submitting}>{submitting ? "Requesting code…" : "Send reset code"}</button>
                </form>
              ) : (
                <form onSubmit={confirmReset}>
                  <label>Six-digit OTP<input inputMode="numeric" pattern="[0-9]{6}" maxLength="6" value={resetOtp} onChange={(event) => setResetOtp(event.target.value.replace(/\D/g, "").slice(0, 6))} autoComplete="one-time-code" required /></label>
                  <label>New password<input type="password" minLength="12" maxLength="128" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" required /><span className="field-hint">Use at least 12 characters.</span></label>
                  <button type="submit" disabled={submitting}>{submitting ? "Updating password…" : "Reset password"}</button>
                  <button type="button" className="secondary-button" disabled={submitting} onClick={() => { setOtpRequested(false); setResetError(""); setResetMessage(""); }}>Request another code</button>
                </form>
              )}
              {resetMessage && <p className="notice success" role="status">{resetMessage}</p>}
              {resetError && <p className="notice error" role="alert">{resetError}</p>}
              <p className="field-hint">For local development without SMS, the development-only OTP is printed in the backend terminal. Do not enable development OTP delivery in production.</p>
            </section>
          )}
          {resetMessage && !resetOpen && <p className="notice success" role="status">{resetMessage}</p>}
          <p className="form-note">New patient? <Link to="/">Create an account</Link></p>
        </section>
      </main>
    </AppShell>
  );
}

function useCurrentPatient() {
  const [patient, setPatient] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchPatient("me")
      .then((value) => {
        if (active) setPatient(value);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return { patient, error, loading };
}

function DashboardPage() {
  const { patient, error, loading } = useCurrentPatient();
  const [qrUrl, setQrUrl] = useState("");
  const [qrError, setQrError] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    fetchPatientQr()
      .then((url) => {
        objectUrl = url;
        if (active) setQrUrl(url);
      })
      .catch((requestError) => {
        if (active) setQrError(requestError.message);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, []);

  return (
    <AppShell>
      <main className="layout">
        {loading && <Loading message="Loading your dashboard…" />}
        {error && <p className="notice error" role="alert">{error}</p>}
        {patient && (
          <>
            <section className="dashboard-heading">
              <div><p className="eyebrow">Patient dashboard</p><h1>Hello, {patient.name}</h1><p className="muted">Your Health ID is ready whenever you need it.</p></div>
              <span className="health-id">{patient.health_id || patient.patient_id}</span>
            </section>
            <div className="dashboard-grid">
              <section className="panel profile-card">
                <div className="section-heading"><div><p className="eyebrow">Profile</p><h2>Your patient profile</h2></div><Link to={`/patients/${patient.patient_id}`}>View profile</Link></div>
                <dl className="details">
                  <Detail label="Health ID" value={patient.health_id || patient.patient_id} />
                  <Detail label="Name" value={patient.name} />
                  <Detail label="Age" value={patient.age} />
                  <Detail label="Gender" value={patient.gender} />
                  <Detail label="Blood group" value={patient.blood_group} />
                  <Detail label="Language" value={patient.language} />
                </dl>
              </section>
              <section className="panel qr-card">
                <p className="eyebrow">Your Health ID</p><h2>Personal QR code</h2>
                <p className="muted">Scan securely after signing in to verify your own record.</p>
                {qrUrl ? <img className="qr-image" src={qrUrl} alt={`Health ID QR code for ${patient.name}`} /> : qrError ? <p className="notice error" role="alert">{qrError}</p> : <Loading message="Generating QR code…" />}
                {qrUrl && <a className="text-link" href={qrUrl} download={`${patient.patient_id}_QR.png`}>Download QR code</a>}
              </section>
            </div>
          </>
        )}
      </main>
    </AppShell>
  );
}

function Detail({ label, value }) {
  return <div className="detail-row"><dt>{label}</dt><dd>{value}</dd></div>;
}

function PatientProfilePage() {
  const { patientId } = useParams();
  const [searchParams] = useSearchParams();
  const [patient, setPatient] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const qrToken = searchParams.get("qr_token");
    const lookup = qrToken
      ? lookupScannedHealthId(patientId, qrToken)
      : fetchPatient(patientId);
    lookup.then((value) => {
      if (active) setPatient(value);
    }).catch((requestError) => {
      if (active) setError(requestError.message);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [patientId, searchParams]);

  return (
    <AppShell>
      <main className="narrow-layout">
        <section className="panel">
          <Link className="back-link" to="/dashboard">← Dashboard</Link>
          <p className="eyebrow">Authorized patient record</p><h1>Patient profile</h1>
          {loading && <Loading message="Verifying Health ID…" />}
          {error && <p className="notice error" role="alert">{error}</p>}
          {patient && <dl className="details">
            <Detail label="Patient ID" value={patient.patient_id} />
            <Detail label="Name" value={patient.name} />
            <Detail label="Age" value={patient.age} />
            <Detail label="Gender" value={patient.gender} />
            <Detail label="Blood group" value={patient.blood_group} />
            <Detail label="Language" value={patient.language} />
          </dl>}
        </section>
      </main>
    </AppShell>
  );
}

function HealthRecordsPage() {
  const [, t] = useAppLanguage();
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({
    category: "diagnosis",
    title: "",
    details: "",
    doctor_name: "",
    doctor_specialization: "General Physician",
    recorded_on: "",
  });

  async function loadRecords() {
    setError("");
    setLoading(true);
    try {
      setRecords(await fetchHealthRecords());
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadRecords();
  }, []);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setSubmitting(true);
    try {
      await createHealthRecord({ ...form, recorded_on: form.recorded_on || null });
      setForm({
        category: "diagnosis",
        title: "",
        details: "",
        doctor_name: "",
        doctor_specialization: "General Physician",
        recorded_on: "",
      });
      setNotice(t.recordAdded);
      await loadRecords();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <main className="layout">
        <section className="dashboard-heading"><div><p className="eyebrow">Private to your account</p><h1>Health records</h1><p className="muted">Add and review your recorded health information.</p></div></section>
        <div className="dashboard-grid records-grid">
          <section className="panel">
            <h2>{t.addRecord}</h2>
            <form onSubmit={submit}>
              <label>{t.recordType}<select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}><option value="diagnosis">Diagnosis</option><option value="medication">Medication</option><option value="allergy">Allergy</option><option value="note">Visit note</option></select></label>
              <label>{t.title}<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} maxLength="120" required /></label>
              <label>{t.details}<textarea value={form.details} onChange={(event) => setForm({ ...form, details: event.target.value })} maxLength="3000" rows="4" required /></label>
              <label>{t.doctorName}<input value={form.doctor_name} onChange={(event) => setForm({ ...form, doctor_name: event.target.value })} maxLength="120" placeholder="e.g. Dr. Ananya Rao" required /></label>
              <label>{t.doctorSpecialization}<select value={form.doctor_specialization} onChange={(event) => setForm({ ...form, doctor_specialization: event.target.value })} required><option>General Physician</option><option>Cardiologist</option><option>Dermatologist</option><option>Pediatrician</option><option>Gynecologist</option></select></label>
              <label>{t.recordedOn}<input type="date" value={form.recorded_on} onChange={(event) => setForm({ ...form, recorded_on: event.target.value })} /></label>
              {notice && <p className="notice success" role="status">{notice}</p>}
              {error && <p className="notice error" role="alert">{error}</p>}
              <button disabled={submitting}>{submitting ? t.savingRecord : t.saveRecord}</button>
            </form>
          </section>
          <section className="panel records-panel"><h2>{t.yourRecords}</h2>
            {loading && <Loading message="Loading health records…" />}
            {!loading && !records.length && <p className="muted">{t.noRecords}</p>}
            {records.map((record) => <article className="record-item" key={record.record_id}>
              <div className="record-meta"><span className={`category category-${record.category}`}>{record.category}</span><time>{record.recorded_on}</time></div>
              <h3>{record.title}</h3><p>{record.details}</p>
              {record.doctor_name && <p className="record-doctor"><strong>Doctor:</strong> {record.doctor_name} · {record.doctor_specialization}</p>}
            </article>)}
          </section>
        </div>
      </main>
    </AppShell>
  );
}

function QrScannerPage() {
  const videoRef = useRef(null);
  const controlsRef = useRef(null);
  const handledScanRef = useRef(false);
  const [scanning, setScanning] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [patient, setPatient] = useState(null);

  useEffect(() => () => controlsRef.current?.stop(), []);

  async function startScanning() {
    setError("");
    setPatient(null);
    handledScanRef.current = false;
    setScanning(true);
    try {
      const { BrowserQRCodeReader } = await import("@zxing/browser");
      const reader = new BrowserQRCodeReader();
      controlsRef.current = await reader.decodeFromVideoDevice(undefined, videoRef.current, async (result, _error, controls) => {
        if (!result || handledScanRef.current) return;
        handledScanRef.current = true;
        controlsRef.current?.stop();
        controls?.stop();
        setScanning(false);
        setLoading(true);
        try {
          const { patientId, qrToken } = decodeHealthIdQr(result.getText());
          const found = await lookupScannedHealthId(patientId, qrToken);
          setPatient(found);
        } catch (scanError) {
          setError(scanError.message);
        } finally {
          setLoading(false);
        }
      });
    } catch {
      setScanning(false);
      setError("Camera access is unavailable. Allow camera access or use a device with a supported browser.");
    }
  }

  return (
    <AppShell>
      <main className="narrow-layout">
        <section className="panel">
          <p className="eyebrow">Health ID verification</p><h1>Scan your QR code</h1>
          <p className="muted">Only the Health ID linked to your current account can be retrieved.</p>
          <div className="scanner-frame"><video ref={videoRef} aria-label="Camera QR scanner" />{!scanning && !loading && <span className="scanner-placeholder">Camera preview appears here</span>}</div>
          {!scanning ? <button onClick={startScanning} disabled={loading}>{loading ? "Verifying Health ID…" : "Start camera scanner"}</button> : <button className="secondary-button" onClick={() => { controlsRef.current?.stop(); setScanning(false); }}>Stop scanning</button>}
          {error && <p className="notice error" role="alert">{error}</p>}
          {patient && <section className="scan-result" aria-live="polite"><p className="eyebrow">Verified for this account</p><h2>{patient.name}</h2><dl className="details"><Detail label="Patient ID" value={patient.patient_id} /><Detail label="Age" value={patient.age} /><Detail label="Gender" value={patient.gender} /><Detail label="Blood group" value={patient.blood_group} /><Detail label="Language" value={patient.language} /></dl><Link className="text-link" to="/records">View my health records</Link></section>}
        </section>
      </main>
    </AppShell>
  );
}

function AssistantPage() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [language, setLanguage] = useState("en");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [speechMessage, setSpeechMessage] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const audioChunksRef = useRef([]);

  const recognitionLocales = { en: "en-IN", te: "te-IN", hi: "hi-IN" };
  const languageNames = { en: "English", te: "Telugu", hi: "Hindi" };

  useEffect(() => () => {
    if (recorderRef.current) {
      recorderRef.current.onstop = null;
      if (recorderRef.current.state !== "inactive") recorderRef.current.stop();
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  async function submit(event) {
    event.preventDefault();
    setError("");
    const submittedQuestion = question.trim();
    if (submittedQuestion.length < 3) {
      setError("Enter a question of at least 3 characters.");
      return;
    }
    setLoading(true);
    try {
      const response = await askRecordAssistant(submittedQuestion, language);
      setMessages((current) => [...current, { question: submittedQuestion, response }]);
      setQuestion("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  async function startListening() {
    setSpeechMessage("");
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setSpeechMessage("Local voice recording is not supported in this browser. Type your question instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = typeof window.MediaRecorder.isTypeSupported === "function"
        ? ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]
          .find((type) => window.MediaRecorder.isTypeSupported(type))
        : undefined;
      const recorder = mimeType
        ? new window.MediaRecorder(stream, { mimeType })
        : new window.MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
        setRecording(false);
        const audio = new Blob(audioChunksRef.current, { type: recorder.mimeType });
        audioChunksRef.current = [];
        if (audio.size === 0) {
          setSpeechMessage("No audio was recorded. Check your microphone and try again.");
          return;
        }
        setTranscribing(true);
        try {
          const result = await transcribeSpeech(audio, language);
          setQuestion(result.text);
        } catch (transcriptionError) {
          setSpeechMessage(transcriptionError.message);
        } finally {
          setTranscribing(false);
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (recordingError) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      recorderRef.current = null;
      setRecording(false);
      const messages = {
        NotAllowedError: "Microphone permission was denied. Allow microphone access in your browser settings or type your question.",
        NotFoundError: "No microphone is available. Connect or enable a microphone, or type your question.",
      };
      setSpeechMessage(messages[recordingError.name] || "Could not start the microphone. Check browser permissions and try again.");
    }
  }

  function stopListening() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  function speakResponse(text) {
    setSpeechMessage("");
    if (!("speechSynthesis" in window) || !window.SpeechSynthesisUtterance) {
      setSpeechMessage("Speech playback is not supported in this browser.");
      return;
    }
    window.speechSynthesis.cancel();
    const voices = window.speechSynthesis.getVoices();
    const voice = voices.find((item) => item.lang.toLowerCase().startsWith(language));
    if (!voice) {
      setSpeechMessage(`No ${languageNames[language]} speech voice is available in this browser.`);
      return;
    }
    const utterance = new window.SpeechSynthesisUtterance(text);
    utterance.voice = voice;
    utterance.lang = recognitionLocales[language];
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => {
      setSpeaking(false);
      setSpeechMessage("The response could not be spoken. Try again or read it on screen.");
    };
    window.speechSynthesis.speak(utterance);
  }

  function stopSpeaking() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    setSpeaking(false);
  }

  return (
    <AppShell>
      <main className="narrow-layout assistant-layout">
        <section className="panel">
          <p className="eyebrow">Private record assistance</p><h1>AI Health Record Assistant</h1>
          <p className="disclaimer">This information is based on your recorded health records and is not a medical diagnosis or a substitute for professional medical advice.</p>
          <label className="language-picker">Response and voice language
            <select value={language} disabled={recording || transcribing} onChange={(event) => { setLanguage(event.target.value); setSpeechMessage(""); }}>
              <option value="en">English</option>
              <option value="te">Telugu</option>
              <option value="hi">Hindi</option>
            </select>
          </label>
          <div className="suggestions"><span>Try asking:</span><button type="button" className="suggestion" onClick={() => setQuestion("What previous diagnoses are recorded?")}>Recorded diagnoses</button><button type="button" className="suggestion" onClick={() => setQuestion("What medicines are listed in my records?")}>Listed medicines</button><button type="button" className="suggestion" onClick={() => setQuestion("What allergies are recorded?")}>Recorded allergies</button></div>
          <form onSubmit={submit}>
            <label>Your question<textarea value={question} onChange={(event) => setQuestion(event.target.value)} minLength="3" maxLength="500" rows="3" required /></label>
            {error && <p className="notice error" role="alert">{error}</p>}
            {speechMessage && <p className="notice error" role="alert">{speechMessage}</p>}
            <div className="assistant-actions">
              {!recording
                ? <button type="button" className="secondary-button" onClick={startListening} disabled={loading || transcribing}>{transcribing ? "Transcribing locally…" : "🎤 Record question"}</button>
                : <button type="button" className="secondary-button" onClick={stopListening}>Stop recording</button>}
              <button disabled={loading || transcribing || question.trim().length < 3}>{loading ? "Searching your records…" : "Send question"}</button>
            </div>
            <p className="field-hint" role="status">
              {recording
                ? `Recording in ${languageNames[language]}…`
                : transcribing
                  ? "Transcribing on the local app server…"
                  : "Audio is sent to the authenticated app server for local transcription and is not saved. First use may take longer while the speech model downloads."}
            </p>
          </form>
          {loading && <Loading message="Retrieving relevant records and preparing an answer…" />}
          <section className="assistant-messages" aria-live="polite" aria-label="Conversation">
            {messages.length === 0 && <p className="muted">AI: Ask a question about information in your health records.</p>}
            {messages.map(({ question: asked, response }, index) => <article className="answer-panel" key={`${index}-${asked}`}>
              <p className="message-label">You · {languageNames[response.language]}</p><p>{asked}</p>
              {response.translated_question && <p className="field-hint">Translated for record search: {response.translated_question}</p>}
              <p className="message-label">AI · Record-based answer</p><p className="assistant-response">{response.answer}</p>
              {response.sources.length > 0 && <><h3>Records used</h3><ul>{response.sources.map((source) => <li key={source.record_id}>{source.category}: {source.title} · {source.recorded_on} <span className="source-id">[{source.record_id}]</span></li>)}</ul></>}
              <p className="field-hint">{response.disclaimer}</p>
              <div className="assistant-actions">
                <button type="button" className="secondary-button" onClick={() => speakResponse(response.answer)}>🔊 Speak Response</button>
                {speaking && <button type="button" className="secondary-button" onClick={stopSpeaking}>Stop Speech</button>}
              </div>
            </article>)}
          </section>
        </section>
      </main>
    </AppShell>
  );
}

function Loading({ message }) {
  return <p className="loading" role="status"><span className="spinner" aria-hidden="true" />{message}</p>;
}

function NotFoundPage() {
  return <AppShell><main className="narrow-layout panel"><h1>Page not found</h1><Link to="/">Return to registration</Link></main></AppShell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RegistrationPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/dashboard" element={<ProtectedPage><DashboardPage /></ProtectedPage>} />
      <Route path="/patients/:patientId" element={<ProtectedPage><PatientProfilePage /></ProtectedPage>} />
      <Route path="/records" element={<ProtectedPage><HealthRecordsPage /></ProtectedPage>} />
      <Route path="/scan" element={<ProtectedPage><QrScannerPage /></ProtectedPage>} />
      <Route path="/assistant" element={<ProtectedPage><AssistantPage /></ProtectedPage>} />
      <Route path="/interpreter" element={<ProtectedPage><AppShell><VoiceInterpreterPage /></AppShell></ProtectedPage>} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
