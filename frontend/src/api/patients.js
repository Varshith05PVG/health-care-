const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000/api";
const SESSION_KEY = "digital-health-record-session";

export function getSession() {
  const value = sessionStorage.getItem(SESSION_KEY);
  if (!value) return null;
  try {
    return JSON.parse(value);
  } catch {
    sessionStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function saveSession(session) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getSession()?.access_token;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch {
    throw new Error("Cannot reach the health record server. Check your connection and try again.");
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    if (response.status === 401 && token) clearSession();
    throw new Error(error.detail || `Request failed with status ${response.status}.`);
  }
  return response;
}

async function requestJson(path, options) {
  const response = await request(path, options);
  return response.json();
}

export function registerPatient(patient) {
  return requestJson("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patient),
  });
}

export function loginPatient(credentials) {
  return requestJson("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });
}

function encodeCredential(value) {
  return btoa(String.fromCharCode(...new Uint8Array(value)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function credentialPayload(credential) {
  return {
    id: credential.id,
    rawId: encodeCredential(credential.rawId),
    type: credential.type,
    response: Object.fromEntries(
      Object.entries(credential.response).map(([key, value]) => [key, encodeCredential(value)]),
    ),
  };
}

export async function registerPasskey() {
  const options = await requestJson("/auth/passkey/register/options", { method: "POST" });
  let credential;
  try {
    credential = await navigator.credentials.create({ publicKey: decodePublicKeyOptions(options) });
  } catch (error) {
    if (error?.name === "NotAllowedError") {
      throw new Error("Face ID was cancelled or is unavailable on this device.");
    }
    throw error;
  }
  if (!credential) throw new Error("Face ID setup did not return a device credential.");
  return requestJson("/auth/passkey/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentialPayload(credential)),
  });
}

export async function loginWithPasskey(credentials) {
  const options = await requestJson("/auth/passkey/login/options", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });
  let assertion;
  try {
    assertion = await navigator.credentials.get({ publicKey: decodePublicKeyOptions(options) });
  } catch (error) {
    if (error?.name === "NotAllowedError") {
      throw new Error("Face ID verification was cancelled or is unavailable on this device.");
    }
    throw error;
  }
  if (!assertion) throw new Error("Face ID verification did not return a device credential.");
  return requestJson("/auth/passkey/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: credentials.identifier, response: credentialPayload(assertion) }),
  });
}

export function enrollFace(descriptor) {
  return requestJson("/auth/face/enroll", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ descriptor }),
  });
}

export function verifyFace(faceToken, descriptor) {
  return requestJson("/auth/face/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ face_token: faceToken, descriptor }),
  });
}

function decodeBase64(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((value.length + 3) % 4);
  return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
}

function decodePublicKeyOptions(options) {
  const publicKey = options.publicKey;
  publicKey.challenge = decodeBase64(publicKey.challenge);
  publicKey.user && (publicKey.user.id = decodeBase64(publicKey.user.id));
  publicKey.excludeCredentials?.forEach((item) => { item.id = decodeBase64(item.id); });
  publicKey.allowCredentials?.forEach((item) => { item.id = decodeBase64(item.id); });
  return publicKey;
}

export function requestPasswordReset(identifier) {
  return requestJson("/auth/forgot-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier }),
  });
}

export function resetPatientPassword(reset) {
  return requestJson("/auth/reset-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reset),
  });
}

export function fetchPatient(patientId) {
  return requestJson(`/patients/${encodeURIComponent(patientId)}`);
}

export function lookupScannedHealthId(patientId, qrToken) {
  return requestJson("/qr/lookup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient_id: patientId, qr_token: qrToken || null }),
  });
}

export function fetchHealthRecords() {
  return requestJson("/records");
}

export function createHealthRecord(record) {
  return requestJson("/records", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(record),
  });
}

export function askRecordAssistant(question, language = "en") {
  return requestJson("/ai/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, language }),
  });
}

function audioFilename(audio, name) {
  const extensions = {
    "audio/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/webm": "webm",
  };
  const mediaType = audio.type.split(";")[0].toLowerCase();
  return `${name}.${extensions[mediaType] || "webm"}`;
}

export function transcribeSpeech(audio, language = "en") {
  const formData = new FormData();
  formData.set("audio", audio, audioFilename(audio, "voice-question"));
  formData.set("language", language);
  return requestJson("/ai/transcribe", {
    method: "POST",
    body: formData,
  });
}

export function interpretSpeech(audio, sourceLanguage, targetLanguage) {
  const formData = new FormData();
  formData.set("audio", audio, audioFilename(audio, "conversation-turn"));
  formData.set("source_language", sourceLanguage);
  formData.set("target_language", targetLanguage);
  return requestJson("/ai/interpret", {
    method: "POST",
    body: formData,
  });
}

export async function fetchPatientQr() {
  const response = await request("/patients/me/qr");
  return URL.createObjectURL(await response.blob());
}
