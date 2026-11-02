import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AccountAvatar } from ".";
import { initialsFromName } from "./account-avatar.mjs";
vi.mock("../../pages/Admin/Users/ProfileAvatar", () => ({
  ProfileAvatar: ({ url, className }: { url: string; className: string }) => (
    <img alt="profile" src={url} className={className} />
  ),
}));
describe("account initials", () => {
  it("keeps Chinese surname/name pairs and Latin initials", () => {
    expect(initialsFromName("张小明")).toBe("小明");
    expect(initialsFromName("Ada Lovelace")).toBe("AL");
  });
  it("switches safely from the name circle to an uploaded image", () => {
    const { rerender } = render(
      <AccountAvatar user={{ display_name: "张小明" }} />,
    );
    expect(screen.getByRole("img", { name: "张小明" })).toHaveTextContent(
      "小明",
    );
    rerender(
      <AccountAvatar
        user={{ display_name: "张小明", avatar_url: "/avatar.png" }}
      />,
    );
    expect(screen.getByRole("img", { name: "profile" })).toHaveClass(
      "octop-account-profile-avatar",
    );
  });
});
