import { describe, expect, it } from "vitest";
import { companionLaunchURL, isCompanionSupported } from "./desktopCompanion";

describe("desktop companion launch boundary", () => {
  it("only forwards known UI actions, never login secrets or backend URLs", () => {
    expect(
      companionLaunchURL(
        "?action=size&token=secret&origin=https://evil.example",
      ),
    ).toBe("octop-companion://size");
    for (const query of [
      "",
      "?action=login",
      "?action=https://evil.example",
      "?action=size%3Ftoken%3Dsecret",
      "?action=open&path=/tmp/file",
    ]) {
      expect(companionLaunchURL(query)).toBe("octop-companion://open");
    }
  });

  it("offers native launch on desktop macOS and Windows", () => {
    expect(
      isCompanionSupported("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"),
    ).toBe(true);
    expect(
      isCompanionSupported("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
    ).toBe(true);
    for (const ua of [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)",
      "Mozilla/5.0 (Linux; Android 15)",
    ]) {
      expect(isCompanionSupported(ua)).toBe(false);
    }
  });
});
