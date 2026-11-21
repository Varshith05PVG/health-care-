# Digital Health Record System — Project Report

## Abstract

The Digital Health Record System is a student project for organizing a patient's basic profile and manually entered health records. A React application communicates with a FastAPI REST API backed by MongoDB and PyMongo. Patients register with a phone number and password, receive a Health ID, and authenticate with either that ID or their phone. Argon2 protects stored passwords and expiring JWTs protect patient-specific APIs. An authenticated QR scanner verifies a patient's own Health ID. An optional local Ollama integration retrieves relevant records belonging to the authenticated patient and asks a language model to summarize only those records. The AI feature is limited to record assistance and is not medical advice or diagnosis.

## Problem statement

Patient details and record categories can be difficult to retrieve across separate interfaces. A simple digital system should allow the patient to register, review their own records, and locate recorded information without making private health data publicly accessible. AI must not create missing diagnoses or expose another patient's information.

## Objectives

- Provide patient account registration and login by phone or Health ID.
- Preserve the existing profile fields and QR Health ID workflow.
- Protect patient-specific profile and record endpoints.
- Store and retrieve basic health-record entries in MongoDB.
- Use QR scanning to identify, validate, and retrieve only the authenticated patient's record.
- Retrieve authorized records before sending minimal context to an optional AI model.
- Validate requests, report service errors, and provide repeatable automated tests.

## Existing system

The original implementation was a small Flask application with a MongoDB/PyMongo connection, a health-check route, a `/patient/{patient_id}` Jinja template showing patient ID/name/age/gender/blood group/language, and a Python `qrcode` script with a hard-coded patient URL. It did not include registration, authentication, saved health-record categories, a QR scanner, or GenAI. Week 6 retained those profile fields, migrated the UI/API, and preserved a compatibility redirect for old `/patient/{patient_id}` QR URLs.

## Proposed system and architecture

```text
React + Vite (browser)
  ├── registration / login / dashboard / records / scanner / assistant
  ├── sessionStorage bearer token
  └── REST over configured API origin
          ↓
FastAPI
  ├── validation and authentication (Argon2 + signed JWT)
  ├── owner-scoped profile, Health ID, and health-record routes
  ├── QR token verification (signed, one-year expiration)
  └── RAG retrieval → local Ollama provider
          ↓                              ↓
MongoDB / PyMongo                  Ollama local HTTP API
  ├── patients                     Only retrieved record excerpts
  └── health_records               No profile demographics sent
```

The React application separates REST helpers, UI routes, and QR parsing. FastAPI separates routes, schemas, settings, security, database dependencies, and provider/retrieval services. MongoDB calls remain behind collection dependencies; Ollama calls remain behind a provider adapter so another model backend can replace it later.

## Technologies used

- **Frontend:** React 18, React Router, Vite, ZXing browser QR reader, Vitest, Testing Library.
- **Backend:** Python, FastAPI, Pydantic, Uvicorn, PyMongo.
- **Persistence:** MongoDB.
- **Security:** `pwdlib` Argon2 password hashing, PyJWT HS256 access and QR tokens, exact-origin CORS.
- **AI:** local Ollama `/api/chat` endpoint; model and URL configured by environment.
- **Testing:** pytest, FastAPI TestClient/httpx2, Vitest/jsdom, Testing Library, npm audit.

## Methodology and algorithms

1. **Registration:** validate profile, phone, and password; normalize the phone; generate a random Health ID; Argon2-hash the password; store the patient; issue an access JWT.
2. **Login:** normalize/select the phone or Health ID; look up one MongoDB patient; verify the Argon2 hash; return a time-limited signed access token or a generic authentication error.
3. **Authorization:** resolve the JWT subject for each protected request. Patient routes query only that subject. A path ID that differs from the subject is rejected before reading another patient's record.
4. **QR:** return an image URL containing the Health ID and a signed QR token with an expiration. Browser camera decoding accepts the system's URL format or a plain Health ID; the API checks the caller's identity, token signature/expiry when supplied, and the stored profile before returning it.
5. **Health-record retrieval:** each database query includes the current JWT patient ID. Record ownership is set on the server, never accepted from a request body.
6. **RAG:** classify simple category terms and rank records by query-word overlap; retrieve up to ten relevant records. Build context from record ID/category/date/title/details only—no name, phone, or demographics—and redact phone/email patterns from excerpt text. If there is no relevant record, return a deterministic “not present” response without calling Ollama. Otherwise the local model is asked to return JSON selections containing exact excerpt quotes. The API verifies each selected quote is an exact substring of a retrieved record and constructs the final answer itself; malformed, invented, or unrelated excerpts are replaced with a conservative fallback.

## Database design

### `patients`

| Field | Use |
| --- | --- |
| `patient_id` | Generated Health ID; unique index. |
| `name`, `age`, `gender`, `blood_group`, `language` | Preserved patient profile fields. |
| `phone` | Normalized login identifier; unique partial index for legacy documents. |
| `password_hash` | Argon2 hash only; never returned by API. |

### `health_records`

| Field | Use |
| --- | --- |
| `record_id` | Random record identifier. |
| `patient_id` | Owning patient ID set from the verified JWT. |
| `category` | `diagnosis`, `medication`, `allergy`, or `note`. |
| `title`, `details` | Patient-entered record information with length validation. |
| `recorded_on` | ISO date supplied by the patient or defaulted to the current date. |
| `created_at` | UTC creation timestamp. |

An index orders records by patient and recorded date. Week 6 patient documents lacking a phone/password are not silently claimable; a trusted operator must independently verify identity before using the backfill script described in the README.

## API description

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/health` | MongoDB connectivity check. |
| `POST` | `/api/auth/register` | Register, hash password, issue token. |
| `POST` | `/api/auth/login` | Authenticate with Health ID or phone. |
| `GET` | `/api/auth/me` | Current account summary. |
| `GET` | `/api/patients/me` | Current profile. |
| `GET` | `/api/patients/{patient_id}` | Own profile only. |
| `GET` | `/api/patients/me/qr` | Own QR as PNG. |
| `POST` | `/api/qr/lookup` | Verify and retrieve scanned Health ID for current patient. |
| `GET` / `POST` | `/api/records` | List/add current patient's health records. |
| `POST` | `/api/ai/query` | Retrieve and summarize authorized records via Ollama. |
| `GET` | `/patient/{patient_id}` | Legacy link redirect; does not query MongoDB. |

All listed endpoints except `/api/health`, registration, login, and the legacy redirect require a bearer access token. Full request/response schemas are available at `/docs`.

## Implementation and integration

The frontend has registration, login, dashboard, profile, health records, QR scanner, and AI assistant screens. Session tokens live in browser session storage and are attached by one API client. The API controls record ownership, so a changed route parameter or Health ID cannot retrieve another patient's information. QR tokens expire after one year; access tokens expire according to configuration. Existing QR generation remains server-side and has an updated configurable command-line helper.

The local model provider is environment-configured with `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_TIMEOUT_SECONDS`. No cloud AI key is used or included. The project also uses MongoDB settings, exact CORS origins, and a private `JWT_SECRET_KEY`; see the README for fresh-machine setup.

## Testing and results

Automated tests use isolated Mongo-like collection doubles and a fake AI provider for deterministic behavior; no real patient data or live model is required by the test suite.

- **Backend:** 16 tests cover registration, duplicate/invalid input, phone/Health ID login, password hashing, protected routes, cross-patient rejection, QR PNG/expiry, record ownership, RAG context isolation/missing data/invalid excerpts, direct-identifier redaction, unavailable model/database, CORS, legacy redirects, and missing signing configuration.
- **Frontend:** 9 tests cover registration input validation and completion/navigation, authentication/network errors, scanner-to-API request behavior, current and legacy QR parsing.
- **Build/security:** `npm run build` succeeds; `npm audit` reports no known frontend dependency advisories at the time of verification.
- **Live MongoDB integration:** a temporary isolated database passed registration, login, protected profile lookup, QR PNG generation, health-record save, and signed QR lookup; the temporary database was dropped afterward.
- **Live API/browser:** the FastAPI health endpoint reported MongoDB connected, Vite rendered the login screen, and an invalid login displayed the expected generic error.
- **Ollama/camera:** local Ollama was not running, so the live AI request correctly returned `503`; the scanner-to-API flow was tested with a mocked browser-camera decoder, not a physical camera.

Test commands:

```powershell
pytest
cd frontend
npm test
npm run build
npm audit
```

## Results

The system now supports a coherent patient-registration-to-dashboard flow, owner-scoped health records, private QR-based identification, and optional grounded record summaries from a local model. Automated validation passed 16 backend tests and 9 frontend tests; the production frontend build and npm audit passed. Live MongoDB integration and API/browser smoke checks passed. Ollama was unavailable during the live check and returned an explicit `503` instead of a successful-looking answer. The AI UI and API state that answers are not professional medical advice.

## Limitations and future scope

- Phone ownership is not SMS/OTP verified. New account registration therefore is not suitable for public production deployment; legacy-account backfill requires a trusted identity-verification procedure.
- No clinician roles, caregiver delegation, password reset, multi-factor login, refresh-token rotation, audit log, consent workflow, or regulatory compliance controls are included.
- The Health ID QR token is signed and expires after one year, but a QR image can still be copied. The patient JWT and owner check remain required to reveal profile data.
- `sessionStorage` reduces persistence after closing a tab but is still exposed to successful same-origin script injection; production should use HTTPS, a reviewed CSP, and consider secure HttpOnly cookies with CSRF protection.
- Local Ollama availability, model behavior, latency, relevance, and answer grounding depend on the selected local model. Citation checks verify referenced record IDs, not every semantic claim.
- Retrieval is a small keyword/category matcher, not a vector database or clinical terminology search. Only the patient's own manually entered records are available.
- Browser QR scanning requires camera permission and a secure context (HTTPS or localhost), supported hardware, and a browser compatible with ZXing.
- The legacy Week 6 records have no phone/password and need operator-assisted account backfill. Data cannot safely be assigned to a new account without verifying ownership.
- No live MongoDB, Ollama, deployment, or real-device camera result is claimed by unit tests.

Future work may add verified phone OTP, clinician-authorized sharing, audit and consent controls, stronger browser security policy, accessibility testing, encrypted backups, deployment hardening, and improved retrieval/evaluation with an approved clinical governance process.

## Conclusion

The final project extends rather than replaces the Week 6 React/FastAPI/MongoDB foundation. Registration, profile display, Health ID QR generation, authentication, patient-owned records, camera scanning, and local record assistance are integrated behind validated REST endpoints. Automated tests verify the important authorization and error-handling boundaries. A production deployment still requires verified identity workflows, service configuration, privacy/security review, and live acceptance testing.

## References

1. React documentation, https://react.dev/
2. Vite documentation, https://vite.dev/guide/
3. FastAPI documentation, https://fastapi.tiangolo.com/
4. PyMongo documentation, https://pymongo.readthedocs.io/
5. MongoDB manual, https://www.mongodb.com/docs/manual/
6. PyJWT documentation, https://pyjwt.readthedocs.io/
7. `pwdlib` documentation, https://frankie567.github.io/pwdlib/
8. ZXing browser library, https://github.com/zxing-js/browser
9. Ollama API documentation, https://docs.ollama.com/api
10. Lewis et al., “Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks,” 2020, https://arxiv.org/abs/2005.11401
