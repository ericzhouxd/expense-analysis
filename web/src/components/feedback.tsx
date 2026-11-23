import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icons";

interface Toast {
  id: number;
  text: string;
  tone: "info" | "error";
  actions: ToastAction[];
}

interface ToastAction {
  label: string;
  run: () => void | Promise<void>;
}

interface ToastApi {
  /** `actions` are offered in order, the likeliest first. */
  show: (text: string, options?: { tone?: Toast["tone"]; actions?: (ToastAction | null)[] }) => void;
  error: (error: unknown) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((items) => items.filter((item) => item.id !== id));
  }, []);

  const show = useCallback<ToastApi["show"]>(
    (text, options = {}) => {
      const id = next.current++;
      const actions = (options.actions ?? []).filter((action) => action !== null);
      setToasts((items) => [...items.slice(-2), { id, text, tone: options.tone ?? "info", actions }]);
      window.setTimeout(() => dismiss(id), actions.length ? 10000 : options.tone === "error" ? 8000 : 4000);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      error: (error) =>
        show(error instanceof Error ? error.message : "Something went wrong. Try again.", {
          tone: "error",
        }),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.tone}`}>
            <span className="grow">{toast.text}</span>
            {toast.actions.map((action) => (
              <button
                key={action.label}
                type="button"
                className="btn small"
                onClick={async () => {
                  dismiss(toast.id);
                  try {
                    await action.run();
                  } catch (error) {
                    api.error(error);
                  }
                }}
              >
                {action.label}
              </button>
            ))}
            <button
              type="button"
              className="btn ghost small icon"
              aria-label="Dismiss"
              onClick={() => dismiss(toast.id)}
            >
              <Icon name="close" size={8} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast needs ToastProvider");
  return api;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** A modal layer: Esc or the backdrop closes it, focus starts inside and is restored. */
export function Modal({
  children,
  onClose,
  label,
  className = "dialog",
}: {
  children: ReactNode;
  onClose: () => void;
  label: string;
  className?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>("[autofocus], input, textarea") ??
      panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
      previous?.focus?.();
    };
  }, []);

  return createPortal(
    <div
      className="backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
        if (event.key === "Tab" && panel.current) {
          const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
          const first = items[0];
          const last = items[items.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <div ref={panel} className={className} role="dialog" aria-modal="true" aria-label={label}>
        {children}
      </div>
    </div>,
    document.body,
  );
}
