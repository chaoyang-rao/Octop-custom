import { beforeEach, expect, it, vi } from "vitest";
import { request } from "../request";
import { enterpriseMcpApi } from "./enterpriseMcp";

vi.mock("../request", () => ({ request: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockResolvedValue({});
});

it("publishes with the server etag rather than an unversioned overwrite", async () => {
  await enterpriseMcpApi.publish("current-etag");
  expect(request).toHaveBeenCalledWith("/enterprise/mcp/admin/publish", {
    method: "POST",
    body: JSON.stringify({ expected_etag: "current-etag" }),
  });
});

it("sends personal credentials only to the local node endpoint", async () => {
  await enterpriseMcpApi.authorize("entry/encoded", {
    token: "private-member-token",
    expected_fingerprint: "a".repeat(64),
  });
  expect(request).toHaveBeenCalledWith(
    "/connectors/enterprise-mcp/entries/entry%2Fencoded/credentials",
    {
      method: "PUT",
      body: JSON.stringify({
        token: "private-member-token",
        expected_fingerprint: "a".repeat(64),
      }),
    },
  );
});

it("removes one local credential binding without deleting the shared catalog entry", async () => {
  await enterpriseMcpApi.clearAuthorization("quality");
  expect(request).toHaveBeenCalledWith(
    "/connectors/enterprise-mcp/entries/quality/credentials",
    { method: "DELETE" },
  );
});
