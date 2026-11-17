import { expect, it } from "vitest";
import {
  enterpriseApprovalPath,
  enterpriseApprovalLoginPath,
  enterpriseDeviceCode,
  enterpriseVerificationUrl,
} from "./enterpriseApproval";

it("preserves only a validated device code across login", () => {
  expect(enterpriseApprovalPath("abcd-efgh")).toBe(
    "/enterprise/approve?code=ABCDEFGH",
  );
  expect(enterpriseApprovalLoginPath("ABCD EFGH")).toBe(
    "/login?enterprise=1&device_code=ABCDEFGH",
  );
  for (const value of [
    "//evil.example",
    "https://evil.example",
    "x&next=/admin",
    "<script>",
  ]) {
    expect(enterpriseDeviceCode(value)).toBe("");
    expect(enterpriseApprovalPath(value)).toBe("/enterprise/approve");
  }
});
it("prefills the short user-code without putting the local poll secret in the URL", () => {
  expect(
    enterpriseVerificationUrl(
      "https://company.example/enterprise/approve",
      "ABCD-EFGH",
    ),
  ).toBe("https://company.example/enterprise/approve?code=ABCDEFGH");
  expect(() =>
    enterpriseVerificationUrl("javascript:alert(1)", "ABCDEFGH"),
  ).toThrow();
});
