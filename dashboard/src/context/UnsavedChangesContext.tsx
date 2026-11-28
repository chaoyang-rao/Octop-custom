import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Modal, theme } from "antd";
import { useTranslation } from "react-i18next";
import {
  useBeforeUnload,
  useBlocker,
  type BlockerFunction,
} from "react-router-dom";

type Action = () => void;

const UnsavedChangesContext = createContext<{
  register: (discard: Action) => () => void;
  confirmDiscard: (action: Action, dirty?: boolean) => void;
} | null>(null);

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const dirtyEditors = useRef(new Set<Action>());
  const [hasDraft, setHasDraft] = useState(false);
  const [pendingAction, setPendingAction] = useState<Action | null>(null);

  const register = useCallback((discard: Action) => {
    dirtyEditors.current.add(discard);
    setHasDraft(true);
    return () => {
      dirtyEditors.current.delete(discard);
      setHasDraft(dirtyEditors.current.size > 0);
    };
  }, []);
  const confirmDiscard = useCallback((action: Action, dirty?: boolean) => {
    if (dirty ?? dirtyEditors.current.size > 0) {
      setPendingAction(() => () => {
        if (dirty === undefined)
          dirtyEditors.current.forEach((discard) => discard());
        action();
      });
    } else {
      action();
    }
  }, []);

  const shouldBlock = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) =>
      dirtyEditors.current.size > 0 &&
      (currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search),
    [],
  );
  const blocker = useBlocker(shouldBlock);

  const blocked = blocker.state === "blocked";
  return (
    <UnsavedChangesContext.Provider value={{ register, confirmDiscard }}>
      {children}
      {hasDraft && <BeforeUnloadGuard />}
      <Modal
        open={blocked || pendingAction !== null}
        // This shared dialog is outside the editor drawers' overlay context.
        zIndex={token.zIndexPopupBase + 1_000}
        title={t("common.unsavedChanges")}
        okText={t("common.discardChanges")}
        cancelText={t("common.keepEditing")}
        okButtonProps={{ danger: true }}
        cancelButtonProps={{ autoFocus: true }}
        onCancel={() => {
          blocker.reset?.();
          setPendingAction(null);
        }}
        onOk={() => {
          setPendingAction(null);
          if (blocked) {
            dirtyEditors.current.forEach((discard) => discard());
            blocker.proceed();
          } else {
            pendingAction?.();
          }
        }}
      >
        {t("common.discardChangesDescription")}
      </Modal>
    </UnsavedChangesContext.Provider>
  );
}

function BeforeUnloadGuard() {
  useBeforeUnload((event) => {
    event.preventDefault();
    event.returnValue = true;
  });
  return null;
}

export function useUnsavedChanges(dirty: boolean, discard: Action) {
  const guard = useContext(UnsavedChangesContext);
  const register = guard?.register;
  const discardRef = useRef(discard);
  useLayoutEffect(() => {
    discardRef.current = discard;
  }, [discard]);
  useLayoutEffect(() => {
    if (dirty) return register?.(() => discardRef.current());
  }, [dirty, register]);

  return (action: Action) => {
    if (guard) guard.confirmDiscard(action, dirty);
    else action();
  };
}

export function useConfirmDiscard() {
  const guard = useContext(UnsavedChangesContext);
  return (action: Action) => {
    if (guard) guard.confirmDiscard(action);
    else action();
  };
}
