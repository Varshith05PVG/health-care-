const HEALTH_ID_PATTERN = /^MW[A-Z0-9_-]{1,38}$/i;

export function decodeHealthIdQr(value) {
  const text = value.trim();
  if (HEALTH_ID_PATTERN.test(text)) return { patientId: text, qrToken: null };

  let parsed;
  try {
    parsed = new URL(text, window.location.origin);
  } catch {
    throw new Error("This QR code does not contain a recognized Health ID.");
  }

  const segments = parsed.pathname.split("/").filter(Boolean);
  const currentLink = segments.length >= 2 && segments[segments.length - 2] === "patients";
  const legacyLink = segments.length >= 2 && segments[segments.length - 2] === "patient";
  if (!currentLink && !legacyLink) {
    throw new Error("This QR code does not contain a recognized Health ID.");
  }

  let patientId;
  try {
    patientId = decodeURIComponent(segments[segments.length - 1]);
  } catch {
    throw new Error("This QR code contains an invalid Health ID.");
  }
  if (!HEALTH_ID_PATTERN.test(patientId)) {
    throw new Error("This QR code contains an invalid Health ID.");
  }
  return { patientId, qrToken: parsed.searchParams.get("qr_token") };
}
