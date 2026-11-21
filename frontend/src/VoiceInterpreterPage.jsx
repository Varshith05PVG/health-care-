import { useEffect, useRef, useState } from "react";
import { interpretSpeech } from "./api/patients.js";

const languages = [
  { code: "en", name: "English" },
  { code: "te", name: "Telugu" },
  { code: "hi", name: "Hindi" },
];

export default function VoiceInterpreterPage() {
  const [source, setSource] = useState("en");
  const [target, setTarget] = useState("te");
  const [recording, setRecording] = useState(false);
  const [interpreting, setInterpreting] = useState(false);
  const [error, setError] = useState("");
  const [turns, setTurns] = useState([]);
  const [speakingTurn, setSpeakingTurn] = useState(null);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const languagesRef = useRef({ source, target });

  languagesRef.current = { source, target };

  useEffect(() => () => {
    if (recorderRef.current) {
      recorderRef.current.onstop = null;
      if (recorderRef.current.state !== "inactive") recorderRef.current.stop();
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  async function startRecording() {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError("Voice recording is not supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const formats = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
      const mimeType = typeof window.MediaRecorder.isTypeSupported === "function"
        ? formats.find((format) => window.MediaRecorder.isTypeSupported(format))
        : undefined;
      const recorder = mimeType
        ? new window.MediaRecorder(stream, { mimeType })
        : new window.MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
        setRecording(false);
        const audio = new Blob(chunksRef.current, { type: recorder.mimeType });
        chunksRef.current = [];
        if (!audio.size) {
          setError("No audio was recorded. Check the microphone and try again.");
          return;
        }
        const pair = languagesRef.current;
        setInterpreting(true);
        try {
          const result = await interpretSpeech(audio, pair.source, pair.target);
          setTurns((current) => [...current, {
            ...result,
            source: pair.source,
            target: pair.target,
          }]);
        } catch (requestError) {
          setError(requestError.message);
        } finally {
          setInterpreting(false);
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (recordingError) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      const messages = {
        NotAllowedError: "Microphone permission was denied. Allow microphone access and try again.",
        NotFoundError: "No microphone is available. Connect or enable a microphone.",
      };
      setError(messages[recordingError.name] || "Could not start recording. Check browser microphone permissions.");
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  function reverseDirection() {
    setSource(target);
    setTarget(source);
    setError("");
  }

  function speakTranslation(turn, index) {
    setError("");
    if (!("speechSynthesis" in window) || !window.SpeechSynthesisUtterance) {
      setError("Speech playback is not supported. Read the translation on screen.");
      return;
    }
    const voice = window.speechSynthesis.getVoices().find((item) =>
      item.lang.toLowerCase().startsWith(turn.target));
    if (!voice) {
      const name = languages.find(({ code }) => code === turn.target)?.name;
      setError(`No ${name} speech voice is installed in this browser. The translation is shown on screen.`);
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new window.SpeechSynthesisUtterance(turn.translation);
    utterance.voice = voice;
    utterance.lang = voice.lang;
    utterance.onstart = () => setSpeakingTurn(index);
    utterance.onend = () => setSpeakingTurn(null);
    utterance.onerror = () => {
      setSpeakingTurn(null);
      setError("The translation could not be spoken. Read it on screen.");
    };
    window.speechSynthesis.speak(utterance);
  }

  function stopSpeaking() {
    window.speechSynthesis.cancel();
    setSpeakingTurn(null);
  }

  const sourceName = languages.find(({ code }) => code === source)?.name;
  const targetName = languages.find(({ code }) => code === target)?.name;

  return (
    <main className="narrow-layout assistant-layout">
      <section className="panel">
        <p className="eyebrow">Turn-by-turn local interpreter</p>
        <h1>Doctor–patient voice interpreter</h1>
        <p className="muted">Record one speaker at a time. Speech is transcribed locally and translated by your local Ollama model.</p>
        <p className="disclaimer">AI translation can be inaccurate. Do not rely on it alone for emergencies, consent, diagnosis, or medication instructions; use a qualified medical interpreter for critical decisions.</p>
        <div className="interpreter-languages">
          <label>Speaker talks in
            <select value={source} disabled={recording || interpreting} onChange={(event) => setSource(event.target.value)}>
              {languages.map(({ code, name }) => <option key={code} value={code} disabled={code === target}>{name}</option>)}
            </select>
          </label>
          <button type="button" className="secondary-button interpreter-switch" disabled={recording || interpreting} onClick={reverseDirection}>
            Reverse direction
          </button>
          <label>Translate for listener
            <select value={target} disabled={recording || interpreting} onChange={(event) => setTarget(event.target.value)}>
              {languages.map(({ code, name }) => <option key={code} value={code} disabled={code === source}>{name}</option>)}
            </select>
          </label>
        </div>
        <p className="interpreter-direction" aria-live="polite">{sourceName} speaker → {targetName} listener</p>
        <div className="assistant-actions interpreter-controls">
          {!recording
            ? <button type="button" disabled={interpreting} onClick={startRecording}>
              {interpreting ? "Transcribing and translating locally…" : `🎤 Record ${sourceName} turn`}
            </button>
            : <button type="button" className="secondary-button" onClick={stopRecording}>Stop and translate</button>}
          {speakingTurn !== null && <button type="button" className="secondary-button" onClick={stopSpeaking}>Stop spoken translation</button>}
        </div>
        {recording && <p className="field-hint" role="status">Recording {sourceName}. Stop when this speaker finishes.</p>}
        {interpreting && <p className="field-hint" role="status">Audio is processed in memory by the local app server and Ollama.</p>}
        {error && <p className="notice error" role="alert">{error}</p>}
        <section className="assistant-messages" aria-live="polite" aria-label="Interpreted conversation">
          {turns.length === 0 && <p className="muted">Interpreted turns will appear here. Reverse direction for the other speaker’s turn.</p>}
          {turns.map((turn, index) => {
            const spokenLanguage = languages.find(({ code }) => code === turn.source)?.name;
            const translatedLanguage = languages.find(({ code }) => code === turn.target)?.name;
            return (
              <article className="answer-panel" key={`${index}-${turn.source}`}>
                <p className="message-label">Spoken · {spokenLanguage}</p>
                <p>{turn.transcript}</p>
                <p className="message-label">Translation · {translatedLanguage}</p>
                <p className="assistant-response" lang={turn.target}>{turn.translation}</p>
                <button type="button" className="secondary-button" onClick={() => speakTranslation(turn, index)}>
                  🔊 Speak translation
                </button>
              </article>
            );
          })}
        </section>
      </section>
    </main>
  );
}
