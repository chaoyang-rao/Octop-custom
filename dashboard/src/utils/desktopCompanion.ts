export function isCompanionSupported(userAgent = navigator.userAgent): boolean {
  return (
    /Macintosh|Windows NT/.test(userAgent) &&
    !/iPhone|iPad|Android/.test(userAgent)
  );
}

export function companionLaunchURL(search: string): string {
  // Only UI actions cross the app boundary. Never forward arbitrary URLs,
  // credentials, paths, backend addresses, or parameters to a native process.
  const action = new URLSearchParams(search).get("action");
  return action === "size"
    ? "octop-companion://size"
    : "octop-companion://open";
}
