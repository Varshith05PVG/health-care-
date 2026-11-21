import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App.jsx";
import {
  clearSession,
  interpretSpeech,
  saveSession,
  transcribeSpeech,
} from "./api/patients.js";
import VoiceInterpreterPage from "./VoiceInterpreterPage.jsx";

const { decodeFromVideoDevice, faceModelLoad, detectSingleFace } = vi.hoisted(() => ({
  decodeFromVideoDevice: vi.fn(),
  faceModelLoad: vi.fn().mockResolvedValue(undefined),
  detectSingleFace: vi.fn(),
}));
vi.mock("@zxing/browser", () => ({
  BrowserQRCodeReader: class {
    decodeFromVideoDevice(...args) {
      return decodeFromVideoDevice(...args);
    }
  },
}));
vi.mock("@vladmandic/face-api", () => ({
  nets: {
    tinyFaceDetector: { loadFromUri: faceModelLoad },
    faceLandmark68TinyNet: { loadFromUri: faceModelLoad },
    faceRecognitionNet: { loadFromUri: faceModelLoad },
  },
  TinyFaceDetectorOptions: class {},
  detectSingleFace,
}));

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

afterEach(() => {
  cleanup();
  clearSession();
  vi.unstubAllGlobals();
});

describe("patient web flow", () => {
  it.each([
    ["audio/webm;codecs=opus", "webm"],
    ["audio/mp4", "mp4"],
    ["audio/ogg;codecs=opus", "ogg"],
  ])("preserves the %s audio format in voice upload filenames", async (type, extension) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ text: "spoken words" }));
    vi.stubGlobal("fetch", fetchMock);
    const audio = new Blob(["recorded audio"], { type });

    await transcribeSpeech(audio, "en");
    const transcriptionUpload = fetchMock.mock.calls[0][1].body.get("audio");
    expect(transcriptionUpload.name).toBe(`voice-question.${extension}`);

    fetchMock.mockResolvedValueOnce(jsonResponse({ transcript: "spoken words", translation: "translated words" }));
    await interpretSpeech(audio, "en", "te");
    const interpretationUpload = fetchMock.mock.calls[1][1].body.get("audio");
    expect(interpretationUpload.name).toBe(`conversation-turn.${extension}`);
  });

  it("validates required registration fields before making a request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><App /></MemoryRouter>);

    await userEvent.click(screen.getByRole("button", { name: "Create patient account" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Full name")).toBeInvalid();
  });

  it("shows an authentication error from the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse({ detail: "The Health ID/phone number or password is incorrect." }, 401),
    ));
    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

    await userEvent.type(screen.getByLabelText("Phone number or Health ID"), "MW123");
    await userEvent.type(screen.getByLabelText("Password"), "incorrect-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("password is incorrect");
  });

  it("requests and confirms a password reset using the same identifier", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ message: "If an account matches, reset instructions have been sent." }, 202))
      .mockResolvedValueOnce(jsonResponse({ message: "Your password has been reset. You can now sign in." }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

    await userEvent.click(screen.getByRole("button", { name: "Forgot Password?" }));
    await userEvent.type(screen.getAllByLabelText("Phone number or Health ID")[1], "HI-P01V01G");
    await userEvent.click(screen.getByRole("button", { name: "Send reset code" }));
    expect(await screen.findByRole("status")).toHaveTextContent("If an account matches");
    await userEvent.type(screen.getByLabelText("Six-digit OTP"), "123456");
    await userEvent.type(screen.getByLabelText(/New password/), "replacement password phrase");
    await userEvent.click(screen.getByRole("button", { name: "Reset password" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Your password has been reset");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ identifier: "HI-P01V01G" });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      identifier: "HI-P01V01G",
      otp: "123456",
      new_password: "replacement password phrase",
    });
  });

  it("registers, enrolls a camera face check, and navigates to the dashboard", async () => {
    const patient = {
      patient_id: "MW123",
      name: "Maya Rao",
      age: 31,
      gender: "Female",
      blood_group: "O+",
      language: "Marathi",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ access_token: "session-token", token_type: "bearer", patient }))
      .mockResolvedValueOnce(jsonResponse({ message: "Camera face verification is set up." }))
      .mockResolvedValueOnce(jsonResponse(patient))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        blob: async () => new Blob(["qr"], { type: "image/png" }),
      });
    vi.stubGlobal("fetch", fetchMock);
    class URLWithBlobSupport extends URL {
      static createObjectURL() { return "blob:health-id-qr"; }
      static revokeObjectURL() {}
    }
    vi.stubGlobal("URL", URLWithBlobSupport);
    render(<MemoryRouter><App /></MemoryRouter>);

    await userEvent.type(screen.getByLabelText("Full name"), patient.name);
    await userEvent.type(screen.getByLabelText("Age"), String(patient.age));
    await userEvent.type(screen.getByLabelText("Gender"), patient.gender);
    await userEvent.type(screen.getByLabelText("Blood group"), patient.blood_group);
    await userEvent.type(screen.getByLabelText("Preferred language"), patient.language);
    await userEvent.type(screen.getByLabelText("Phone number"), "+919876543210");
    await userEvent.type(screen.getByLabelText(/Password/), "a-long-test-password");
    await userEvent.click(screen.getByRole("button", { name: "Create patient account" }));
    expect(await screen.findByRole("heading", { name: "Set up camera face check" })).toBeInTheDocument();

    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    detectSingleFace.mockReturnValue({
      withFaceLandmarks: () => ({
        withFaceDescriptor: async () => ({ descriptor: new Float32Array(128) }),
      }),
    });
    await userEvent.click(screen.getByRole("button", { name: "Start camera" }));
    await userEvent.click(await screen.findByRole("button", { name: "Scan face" }));

    expect(await screen.findByRole("heading", { name: "Hello, Maya Rao" })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).descriptor).toHaveLength(128);
    expect(screen.getByAltText("Health ID QR code for Maya Rao")).toBeInTheDocument();
  });

  it("shows network failures clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

    await userEvent.type(screen.getByLabelText("Phone number or Health ID"), "MW123");
    await userEvent.type(screen.getByLabelText("Password"), "long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the health record server");
  });

  it("scans a Health ID QR and sends the decoded ID and token to the API", async () => {
    const patient = {
      patient_id: "MW123",
      name: "Maya Rao",
      age: 31,
      gender: "Female",
      blood_group: "O+",
      language: "Marathi",
    };
    saveSession({ access_token: "test-session" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(patient)));
    decodeFromVideoDevice.mockImplementation(async (_device, _video, onResult) => {
      await onResult({ getText: () => "http://localhost:5173/patients/MW123?qr_token=signed-qr-token" });
      return { stop: vi.fn() };
    });
    render(<MemoryRouter initialEntries={["/scan"]}><App /></MemoryRouter>);

    await userEvent.click(screen.getByRole("button", { name: "Start camera scanner" }));

    expect(await screen.findByText("Verified for this account")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Maya Rao" })).toBeInTheDocument();
    const [url, options] = fetch.mock.calls[0];
    expect(url).toContain("/qr/lookup");
    expect(JSON.parse(options.body)).toEqual({ patient_id: "MW123", qr_token: "signed-qr-token" });
    expect(options.headers.get("Authorization")).toBe("Bearer test-session");
  });

  it("sends typed questions and the selected language to the record assistant", async () => {
    saveSession({ access_token: "test-session" });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
      answer: "Medicine: Take one tablet daily.",
      sources: [],
      language: "hi",
      disclaimer: "Record assistance only.",
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/assistant"]}><App /></MemoryRouter>);

    await userEvent.selectOptions(screen.getByLabelText("Response and voice language"), "hi");
    await userEvent.type(screen.getByLabelText("Your question"), "मेरी दवाइयाँ कौन सी हैं?");
    await userEvent.click(screen.getByRole("button", { name: "Send question" }));

    expect(await screen.findByText("Medicine: Take one tablet daily.")).toBeInTheDocument();
    expect(screen.getByText(/This information is based on your recorded health records/)).toBeInTheDocument();
    const [, options] = fetchMock.mock.calls.find(([url]) => url.endsWith("/ai/query"));
    expect(JSON.parse(options.body)).toEqual({ question: "मेरी दवाइयाँ कौन सी हैं?", language: "hi" });
  });

  it.each([
    ["te", "మందుల వివరాలు ఏమిటి?"],
    ["hi", "दवाइयाँ क्या हैं?"],
  ])("records and transcribes a %s voice question locally", async (language, transcript) => {
    saveSession({ access_token: "test-session" });
    const stream = { getTracks: () => [{ stop: vi.fn() }] };
    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    });
    let recorder;
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor(_stream, options) {
        this.mimeType = options.mimeType;
        this.state = "inactive";
        recorder = this;
      }
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        this.ondataavailable({ data: new Blob(["mock-audio"], { type: this.mimeType }) });
        this.onstop();
      }
    }
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ text: transcript }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/assistant"]}><App /></MemoryRouter>);

    expect(screen.queryByRole("region", { name: "AI service status" })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Response and voice language"), language);
    await userEvent.click(screen.getByRole("button", { name: "🎤 Record question" }));
    expect(await screen.findByRole("button", { name: "Stop recording" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stop recording" }));

    await waitFor(() => expect(screen.getByLabelText("Your question")).toHaveValue(transcript));
    const [url, options] = fetchMock.mock.calls.find(([requestUrl]) => requestUrl.endsWith("/ai/transcribe"));
    expect(url).toContain("/ai/transcribe");
    expect(options.body.get("language")).toBe(language);
    expect(options.body.get("audio")).toBeInstanceOf(Blob);
    expect(fetchMock.mock.calls.some(([requestUrl]) => requestUrl.endsWith("/ai/query"))).toBe(false);
  });

  it("explains when microphone permission is denied", async () => {
    saveSession({ access_token: "test-session" });
    const denied = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(denied) },
    });
    vi.stubGlobal("MediaRecorder", class {});
    vi.stubGlobal("fetch", vi.fn());
    render(<MemoryRouter initialEntries={["/assistant"]}><App /></MemoryRouter>);

    await userEvent.click(screen.getByRole("button", { name: "🎤 Record question" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone permission was denied");
  });

  it("interprets turns in both directions for the doctor and patient", async () => {
    saveSession({ access_token: "test-session" });
    const stream = { getTracks: () => [{ stop: vi.fn() }] };
    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    });
    let recorder;
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor(_stream, options) {
        this.mimeType = options.mimeType;
        this.state = "inactive";
        recorder = this;
      }
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        this.ondataavailable({ data: new Blob(["mock-audio"], { type: this.mimeType }) });
        this.onstop();
      }
    }
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        transcript: "I have pain.",
        translation: "నాకు నొప్పిగా ఉంది.",
      }))
      .mockResolvedValueOnce(jsonResponse({
        transcript: "నాకు నొప్పిగా ఉంది.",
        translation: "मुझे दर्द हो रहा है।",
      }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><VoiceInterpreterPage /></MemoryRouter>);

    await userEvent.click(screen.getByRole("button", { name: "🎤 Record English turn" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop and translate" }));
    expect(await screen.findByText("నాకు నొప్పిగా ఉంది.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Reverse direction" }));
    expect(screen.getByRole("button", { name: "🎤 Record Telugu turn" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "🎤 Record Telugu turn" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop and translate" }));
    expect(await screen.findByText("मुझे दर्द हो रहा है।")).toBeInTheDocument();

    const interpretationRequests = fetchMock.mock.calls
      .filter(([url]) => url.endsWith("/ai/interpret"));
    expect(interpretationRequests).toHaveLength(2);
    expect(interpretationRequests[0][1].body.get("source_language")).toBe("en");
    expect(interpretationRequests[0][1].body.get("target_language")).toBe("te");
    expect(interpretationRequests[1][1].body.get("source_language")).toBe("te");
    expect(interpretationRequests[1][1].body.get("target_language")).toBe("en");
  });

  it("speaks an answer with the selected language voice and can stop playback", async () => {
    saveSession({ access_token: "test-session" });
    const voice = { lang: "hi-IN" };
    let spokenUtterance;
    const synthesis = {
      cancel: vi.fn(),
      getVoices: () => [voice],
      speak: (utterance) => {
        spokenUtterance = utterance;
        utterance.onstart();
      },
    };
    class MockUtterance {
      constructor(text) { this.text = text; }
    }
    vi.stubGlobal("speechSynthesis", synthesis);
    vi.stubGlobal("SpeechSynthesisUtterance", MockUtterance);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
      answer: "Take one tablet daily.",
      sources: [],
      language: "hi",
      disclaimer: "Record assistance only.",
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/assistant"]}><App /></MemoryRouter>);

    await userEvent.selectOptions(screen.getByLabelText("Response and voice language"), "hi");
    await userEvent.type(screen.getByLabelText("Your question"), "मेरी दवाइयाँ कौन सी हैं?");
    await userEvent.click(screen.getByRole("button", { name: "Send question" }));
    await screen.findByText("Take one tablet daily.");
    await userEvent.click(screen.getByRole("button", { name: "🔊 Speak Response" }));

    expect(spokenUtterance.voice).toBe(voice);
    expect(spokenUtterance.lang).toBe("hi-IN");
    await userEvent.click(await screen.findByRole("button", { name: "Stop Speech" }));
    expect(synthesis.cancel).toHaveBeenCalled();
  });

  it("does not speak with an unavailable selected-language voice", async () => {
    saveSession({ access_token: "test-session" });
    const synthesis = { cancel: vi.fn(), getVoices: () => [{ lang: "en-US" }], speak: vi.fn() };
    class MockUtterance {}
    vi.stubGlobal("speechSynthesis", synthesis);
    vi.stubGlobal("SpeechSynthesisUtterance", MockUtterance);
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(jsonResponse({
      answer: "Take one tablet daily.",
      sources: [],
      language: "te",
      disclaimer: "Record assistance only.",
    })));
    render(<MemoryRouter initialEntries={["/assistant"]}><App /></MemoryRouter>);

    await userEvent.selectOptions(screen.getByLabelText("Response and voice language"), "te");
    await userEvent.type(screen.getByLabelText("Your question"), "మందులు ఏమిటి?");
    await userEvent.click(screen.getByRole("button", { name: "Send question" }));
    await screen.findByText("Take one tablet daily.");
    await userEvent.click(screen.getByRole("button", { name: "🔊 Speak Response" }));

    expect(synthesis.speak).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("No Telugu speech voice is available");
  });
});
