import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DesktopChromeProvider } from "../../hooks/useDesktopChrome";
import { WINDOW_CONTROLS_SPACER_ATTR } from "../../utils/desktopChrome";
import ChatDockPanelShell from "./ChatDockPanelShell";

const baseProps = {
  onModeChange: vi.fn(),
  onClose: vi.fn(),
  children: <div>dock-body</div>,
};

function renderShell(
  mode: "right" | "popup" | "bottom",
  chrome: "mac" | "windows" | null,
) {
  return render(
    <DesktopChromeProvider value={chrome}>
      <ChatDockPanelShell {...baseProps} mode={mode} />
    </DesktopChromeProvider>,
  );
}

describe("ChatDockPanelShell chrome inset", () => {
  it("leaves right-dock and popup toolbars clear with window controls on the left", () => {
    const { container, rerender } = renderShell("right", "mac");
    expect(
      container.querySelector(`[${WINDOW_CONTROLS_SPACER_ATTR}]`),
    ).toBeNull();

    rerender(
      <DesktopChromeProvider value="windows">
        <ChatDockPanelShell {...baseProps} mode="popup" />
      </DesktopChromeProvider>,
    );
    expect(
      container.querySelector(`[${WINDOW_CONTROLS_SPACER_ATTR}]`),
    ).toBeNull();

    rerender(
      <DesktopChromeProvider value="mac">
        <ChatDockPanelShell {...baseProps} mode="bottom" />
      </DesktopChromeProvider>,
    );
    expect(
      container.querySelector(`[${WINDOW_CONTROLS_SPACER_ATTR}]`),
    ).toBeNull();
  });

  it("does not reserve window-control space outside the desktop shell", () => {
    const { container } = renderShell("right", null);
    expect(
      container.querySelector(`[${WINDOW_CONTROLS_SPACER_ATTR}]`),
    ).toBeNull();
  });

  it("disables popup mask while an overlay menu is open", () => {
    const onClose = vi.fn();
    const { container } = render(
      <DesktopChromeProvider value={null}>
        <ChatDockPanelShell
          {...baseProps}
          mode="popup"
          onClose={onClose}
          overlayMenuOpen
        />
      </DesktopChromeProvider>,
    );
    const mask = container.querySelector("[aria-hidden]") as HTMLElement;
    expect(mask.style.pointerEvents).toBe("none");
    mask.click();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps the layout menu open when the dock style object is replaced", async () => {
    const style = { width: 560 };
    const { rerender } = render(
      <DesktopChromeProvider value={null}>
        <ChatDockPanelShell {...baseProps} mode="right" style={style} />
      </DesktopChromeProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "面板布局" }));
    expect(
      await screen.findByRole("menuitem", {
        name: "browserWorkspace.panelBottom",
      }),
    ).toBeInTheDocument();

    rerender(
      <DesktopChromeProvider value={null}>
        <ChatDockPanelShell
          {...baseProps}
          mode="right"
          style={{ width: style.width }}
        />
      </DesktopChromeProvider>,
    );

    expect(
      screen.getByRole("menuitem", { name: "browserWorkspace.panelBottom" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "browserWorkspace.panelPopup" }),
    ).toBeInTheDocument();
  });
});
