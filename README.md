# Digital Health Record System

A student-project health-record application with a React/Vite frontend, FastAPI REST API, MongoDB/PyMongo persistence, patient login, signed Health ID QR codes, camera QR scanning, and a local Ollama record-assistance workflow.

Health care web application for digital health record storage and language translation support.

The AI assistant retrieves matching records for the authenticated patient before generating an answer. It is for record assistance only—not diagnosis, treatment, or professional medical advice. No authentication provider, SMS verification, QR scanning of other patients' records, cloud AI provider, or GenAI/RAG framework is configured.

## Features

- Patient registration with phone number, Health ID, and password login.
- Argon2 password hashing and expiring HS256 JWT access tokens.
- Patient profile, Health ID QR generation, and browser-camera QR scanning (including existing Week 6 QR links).
- Patient-owned health-record entries for diagnoses, medications, allergies, and notes.
- Optional camera face matching after password login. It stores a face descriptor (not a photo) in MongoDB; it has no liveness detection and is a prototype, not production-grade biometric security.
- MongoDB retrieval before local Ollama responses, with source references and a missing-information fallback.
- English record-assistant answers from local Ollama; local Telugu/Hindi translation with optional Bhashini or Google Translation; and a turn-by-turn English/Telugu/Hindi voice interpreter using local transcription and TranslateGemma.
- Form validation, loading indicators, API error messages, exact-origin CORS, and API test coverage.

## Technology stack and prerequisites

- Python 3.11 or newer
- Node.js 22.12+ (required by the pinned Vitest major)
- MongoDB 6+ (local or hosted)
- Ollama installed and running locally for AI queries; model `llama3.2:3b` by default

## Project structure

```text
PVG Digital health record/
├── backend/
│   ├── app/
│   │   ├── routes/       # auth, patient/QR, records, AI API routes
│   │   ├── services/     # Ollama adapter, QR generation, RAG retrieval
│   │   ├── config.py     # environment-backed settings
│   │   ├── db.py         # PyMongo collection dependencies/indexes
│   │   ├── schemas.py    # request/response validation
│   │   ├── security.py   # Argon2 and JWT helpers
│   │   └── main.py       # FastAPI application and MongoDB lifecycle
│   ├── scripts/          # trusted legacy-account credential backfill
│   └── tests/            # backend API/security tests
├── frontend/
│   ├── src/
│   │   ├── api/          # REST client and session handling
│   │   ├── utils/        # Health ID QR parser
│   │   ├── App.jsx       # registration, login, dashboard, records, scan, AI
│   │   └── styles.css    # responsive interface
│   ├── package.json
│   └── vite.config.js
├── .env.example
├── package.json          # root `npm run dev` all-services launcher
├── scripts/dev.mjs       # starts MongoDB check, API, Vite, Ollama, and model pull
├── requirements.txt
├── requirements-dev.txt
├── app.py                # compatibility launcher
└── generate_qr.py        # QR command-line helper
```

## Environment variables

Copy root `.env.example` to `.env` and set:

| Variable | Purpose |
| --- | --- |
| `MONGODB_URI` | MongoDB connection string. Keep credentials private. |
| `MONGODB_DATABASE` | Database name; defaults to `health_db`. |
| `FRONTEND_BASE_URL` | Publicly reachable frontend URL embedded in generated QR codes. |
| `CORS_ORIGINS` | Comma-separated, exact permitted browser origins. |
| `JWT_SECRET_KEY` | Private random signing key, at least 32 characters. Required for registration, login, and QR-token verification. |
| `JWT_ACCESS_TOKEN_MINUTES` | Access-token lifetime; defaults to 60 minutes. |
| `PASSWORD_RESET_MODE` | `disabled` (default, production-safe without SMS) or `development`; development prints the OTP in the backend terminal and must not be used in production. |
| `PASSWORD_RESET_OTP_MINUTES` | OTP expiry, defaults to 5 minutes (maximum 15). |
| `PASSWORD_RESET_MAX_ATTEMPTS` | Maximum OTP verifications, defaults to 5. |
| `OLLAMA_BASE_URL` | Local Ollama URL; defaults to `http://localhost:11434`. |
| `OLLAMA_MODEL` | Installed local model name; defaults to `llama3.2:3b`. |
| `OLLAMA_TRANSLATION_MODEL` | Local TranslateGemma model for interpreter and assistant translations; defaults to `translategemma:4b`. |
| `OLLAMA_TIMEOUT_SECONDS` | Model request timeout; defaults to 60 seconds. |
| `BHASHINI_API_URL` | Optional Bhashini ULCA model-pipeline endpoint, typically `https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline`. Leave blank unless configured. |
| `BHASHINI_USER_ID` / `BHASHINI_API_KEY` | Optional private Bhashini credentials. Never put these in frontend environment variables. |
| `BHASHINI_PIPELINE_ID` | Bhashini pipeline ID enabled for the account and translation task. |
| `GOOGLE_TRANSLATE_API_KEY` | Optional Google Cloud Translation API key; used only on the backend when configured. |
| `TRANSLATION_TIMEOUT_SECONDS` | Timeout for configured Bhashini or Google Translation requests; defaults to 20 seconds. |

The record assistant and voice interpreter use the local TranslateGemma model for Telugu/Hindi translations by default, so no external translation credentials are needed. Bhashini and Google Cloud Translation remain optional for the record assistant and are preferred when configured. Translation text stays on the local app server when the local model is used. The AI health endpoint reports whether local or configured translation is available without returning credentials.

Start Ollama in a separate terminal, then download the configured model once:

```powershell
ollama serve
ollama pull llama3.2:3b
ollama pull translategemma:4b
```

Set the model variables to the exact model tags downloaded with `ollama pull`. The record assistant uses `OLLAMA_MODEL`; voice interpretation and local assistant translation use `OLLAMA_TRANSLATION_MODEL`. Translation provider keys are optional and belong only in the backend `.env`.

Copy `frontend/.env.example` to `frontend/.env`:

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | API root for the frontend; defaults to `http://localhost:5000/api`. |

Generate a private signing secret without printing it in PowerShell:

```powershell
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 48
$rng.GetBytes($bytes)
$secret = [Convert]::ToBase64String($bytes)
$rng.Dispose()
Add-Content .env "JWT_SECRET_KEY=$secret"
```

The root `.gitignore` excludes `.env`, `.env.*`, virtual environments, `node_modules`, caches, and build output. The checked-in example file is intentionally only a placeholder; replace the example JWT value in your local `.env`. Do not commit actual environment files.

## One-command local development

On Windows, once Node.js and Python are installed, start MongoDB if needed and run this from the project root:

```powershell
npm run dev
```

The launcher creates a private `.env` and JWT secret if missing, installs backend/frontend dependencies if missing, starts MongoDB's Windows service when necessary, starts or reuses Ollama and downloads the configured model if absent, then starts the FastAPI API and Vite frontend. First-time Python/package/model downloads require internet and may take longer than two minutes; model download time depends on the connection. The launcher prints `http://127.0.0.1:5173` when ready. Press Ctrl+C to stop services started by that launcher.

Telugu/Hindi translation works locally with the configured TranslateGemma model; Bhashini or Google Cloud Translation credentials are optional. The launcher does not invent credentials or enable a fake translator.

## Fresh-machine installation and run

1. Start MongoDB and create or select a database (default `health_db`). The application creates unique patient/phone indexes and a patient/date record index when needed.
2. From the repository root, create and activate a virtual environment, install backend packages, and configure `.env`:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
   Copy-Item .env.example .env
   # Edit .env and set a private JWT_SECRET_KEY and your MongoDB URI.
   ```

3. Start the backend from the repository root:

   ```powershell
   uvicorn backend.app.main:app --reload --port 5000
   ```

   API documentation: `http://localhost:5000/docs`; health probe: `http://localhost:5000/api/health`.

4. Install and start the frontend in another terminal:

   ```powershell
   cd frontend
   Copy-Item .env.example .env
   npm install
   npm run dev
   ```

   Open the Vite URL printed by the command (normally `http://localhost:5173`). Change `FRONTEND_BASE_URL`, `CORS_ORIGINS`, and `VITE_API_BASE_URL` together when hosting on another origin.

5. For English AI queries, start Ollama and download the configured local model (the root `npm run dev` launcher can do this automatically):

   ```powershell
   ollama serve
   ```

   In another terminal:

   ```powershell
   ollama pull llama3.2:3b
   ```

   Set `OLLAMA_MODEL` to a model installed locally if using a different model. AI requests return a clear `503` if Ollama or that configured model is unavailable. Ollama is only the local answer-generation model, not a translator.

The assistant uses `POST /api/ai/query` with `{"question":"...","language":"en"}`, where language is `en`, `te`, or `hi`. Telugu/Hindi responses require an available Bhashini translation pipeline or a Google Cloud Translation API key. To enable Bhashini, set the Bhashini endpoint, user ID, API key, and pipeline ID supplied for your account; do not use example credentials. The endpoint derives patient scope only from the authenticated bearer token and rejects extra request fields such as `patient_id`. `GET /api/ai/health` reports Ollama/model and translation-provider reachability without exposing credentials.

Patient login accepts a registered phone number or Health ID at `POST /api/auth/login`. New accounts keep the existing internal `patient_id` for record ownership and QR compatibility, and receive a sequential Health ID such as `HI-P01V01G`, `HI-P02V02G`. Passwords are Argon2-hashed. Password reset uses `POST /api/auth/forgot-password` followed by `POST /api/auth/reset-password`; set `PASSWORD_RESET_MODE=development` for local testing and read the OTP from the backend terminal. Reset requests always return the same generic message. No SMS provider is configured; use `PASSWORD_RESET_MODE=disabled` outside local development until an SMS sender is integrated.

Voice input records audio in the browser and sends it to the authenticated application API, where `faster-whisper` transcribes it locally on the backend CPU. It supports English, Telugu, and Hindi and does not use the browser's online speech-recognition service. The default multilingual `tiny` model is downloaded by the backend on its first transcription, so the server needs internet access for that first use; later transcriptions run locally. Set `WHISPER_MODEL` to another supported Whisper model name if needed. Audio is used for transcription and is not retained by the app. Browser-native SpeechSynthesis is still used for spoken responses and depends on installed browser voices; typed questions remain available.

The authenticated **Voice interpreter** page provides tap-to-record, turn-by-turn interpretation for English, Telugu, and Hindi in either direction. Speech transcription uses the local Whisper model; translation uses the dedicated local TranslateGemma model and does not require Bhashini/Google credentials. The translated text is displayed and can be spoken using browser-native SpeechSynthesis when a voice for that language is installed. Audio is processed in memory and is not retained. This is an AI aid, not a qualified medical interpreter; verify critical instructions, consent, and emergency communication with a professional.

To create a signed QR PNG from the command line for an existing Health ID, configure the same `JWT_SECRET_KEY` and frontend URL, then run from the repository root:

```powershell
python generate_qr.py MW001
```

## Authentication and legacy patient accounts

New accounts are created from the registration screen with a phone number and password of at least 12 characters. The password is hashed using Argon2 before storage. Patients can sign in with their Health ID or phone number. JWT tokens are kept in browser `sessionStorage` and sent as bearer tokens; sessions expire according to `JWT_ACCESS_TOKEN_MINUTES`.

Week 6 patient documents have no verified phone number or password. They are **not** automatically claimable through public registration. A trusted operator must independently verify the patient and run:

```powershell
python -m backend.scripts.backfill_patient_account MW001
```

The command prompts for the verified phone and a new password without echoing the password. Do not run it until identity verification is complete. The operator should communicate the new password using a separate secure channel.

## API overview

Protected endpoints require `Authorization: Bearer <access_token>` and return data only for the token's patient.

| Method | Endpoint | Access | Description |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Public | API/MongoDB connectivity. |
| `POST` | `/api/auth/register` | Public | Create account and issue an access token. |
| `POST` | `/api/auth/login` | Public | Login by Health ID or phone and password. |
| `POST` | `/api/auth/forgot-password` | Public | Request an OTP; response does not reveal whether the patient exists. |
| `POST` | `/api/auth/reset-password` | Public | Verify OTP and replace the password. |
| `GET` | `/api/auth/me` | Patient | Current patient account summary. |
| `POST` | `/api/patients` | Public compatibility alias | Same account-registration behavior as `/api/auth/register`. |
| `GET` | `/api/patients/me` | Patient | Current patient's profile. |
| `GET` | `/api/patients/{patient_id}` | Patient, own ID only | Patient profile; other IDs return `403`. |
| `GET` | `/api/patients/me/qr` | Patient | Generate a PNG QR with a signed, expiring Health ID token. |
| `POST` | `/api/qr/lookup` | Patient, own ID only | Verify QR token if supplied and retrieve the logged-in patient's profile. |
| `GET` | `/api/records` | Patient | List only the signed-in patient's health records. |
| `POST` | `/api/records` | Patient | Add a diagnosis, medication, allergy, or note to own records. |
| `POST` | `/api/ai/query` | Patient | Retrieve authorized context, then ask the configured local Ollama model. |
| `GET` | `/patient/{patient_id}` | Public compatibility redirect | Redirect old Week 6 QR links to the React profile route without querying MongoDB. |

Input validation errors return `422`; duplicate phones return `409`; unauthorized and cross-patient access returns `401`/`403`; unknown or expired QR values are rejected; unavailable MongoDB/Ollama services return `503`.

## Testing

From the repository root:

```powershell
.\venv\Scripts\Activate.ps1
pytest
```

Frontend unit/workflow tests and production build:

```powershell
cd frontend
npm test
npm run build
npm audit
```

Backend tests use isolated in-memory collection doubles and a fake AI provider; they cover registration, login, password hashing, patient ownership, QR generation/expiry, health records, RAG scoping, CORS, validation, and service failures. Frontend tests cover form validation, registration/navigation, login errors, offline errors, camera-scan API calls, and current/legacy QR parsing. The final workflow was also exercised against a temporary MongoDB database. Ollama and a physical device camera still need to be available for live acceptance tests.

To exercise forgot password locally, set `PASSWORD_RESET_MODE=development` in `.env` and restart the backend. Request a code from the login screen; the random, five-minute OTP is printed only in the backend terminal, never returned by the public endpoint. Successful reset invalidates the OTP; five failed attempts also exhaust it. The checked-in `.env.example` leaves reset delivery disabled.

## Demo flow

1. Register a patient and note the generated Health ID.
2. Confirm the dashboard profile and QR image load.
3. Add diagnosis/medication/allergy sample records on **Health records**.
4. Sign out and sign in using phone or Health ID plus password.
5. Scan the patient's QR from **Scan Health ID** (allow browser camera access).
6. Query **Record assistant** about an item actually recorded; verify the cited source.
7. Try another patient's Health ID while signed in—the API must deny access.

See [docs/PROJECT_REPORT.md](./docs/PROJECT_REPORT.md) for the project abstract, problem statement, methodology, architecture, database design, testing results, limitations, future scope, and references.
