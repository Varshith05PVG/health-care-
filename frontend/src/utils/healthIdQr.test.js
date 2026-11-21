import { describe, expect, it } from "vitest";
import { decodeHealthIdQr } from "./healthIdQr.js";

describe("Health ID QR decoding", () => {
  it("accepts a plain Health ID", () => {
    expect(decodeHealthIdQr("MW123abc")).toEqual({ patientId: "MW123abc", qrToken: null });
  });

  it("extracts the Health ID and signed token from a generated URL", () => {
    expect(decodeHealthIdQr("https://records.example/patients/MW123?qr_token=signed-token")).toEqual({
      patientId: "MW123",
      qrToken: "signed-token",
    });
  });

  it("accepts an older Week 6 patient QR link", () => {
    expect(decodeHealthIdQr("http://192.168.0.105:5000/patient/MW001")).toEqual({
      patientId: "MW001",
      qrToken: null,
    });
  });

  it("rejects malformed or unrelated QR values", () => {
    expect(() => decodeHealthIdQr("https://example.com/not-a-health-id")).toThrow("recognized Health ID");
    expect(() => decodeHealthIdQr("MW" + "x".repeat(50))).toThrow("recognized Health ID");
  });
});
