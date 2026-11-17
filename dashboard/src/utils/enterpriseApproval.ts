/** Carry only a device user-code through company login, never an arbitrary redirect. */
export function enterpriseDeviceCode(raw: string | null | undefined): string {
  const code = (raw ?? "").replace(/[\s-]/g, "").toUpperCase();
  return /^[A-Z0-9]{8}$/.test(code) ? code : "";
}

export function enterpriseApprovalPath(raw?: string | null): string {
  const code = enterpriseDeviceCode(raw);
  return (
    "/enterprise/approve" + (code ? `?code=${encodeURIComponent(code)}` : "")
  );
}

export function enterpriseApprovalLoginPath(raw?: string | null): string {
  const code = enterpriseDeviceCode(raw);
  return (
    "/login?enterprise=1" +
    (code ? `&device_code=${encodeURIComponent(code)}` : "")
  );
}

export function enterpriseVerificationUrl(uri: string, code: string): string {
  const url = new URL(uri);
  if (url.protocol !== "https:" && url.protocol !== "http:")
    throw new Error("Invalid sign-in address");
  const valid = enterpriseDeviceCode(code);
  if (valid) url.searchParams.set("code", valid);
  return url.toString();
}
