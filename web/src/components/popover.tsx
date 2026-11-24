import { type ReactNode, type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";

const GAP = 6;
const EDGE = 10;

/**
 * The one panel behind every list, menu and calendar. It sits in the browser's top
 * layer beside its anchor, so no card, table or dialog can clip it, and keeps its
 * clicks and keys from whatever it is drawn inside.
 */
export function Popover({
  anchor,
  onClose,
  children,
  className = "",
  align = "start",
  match = false,
}: {
  anchor: RefObject<HTMLElement | null>;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  align?: "start" | "end";
  /** At least as wide as the anchor. */
  match?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number; minWidth?: number; maxHeight: number } | null>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useLayoutEffect(() => {
    const element = panel.current;
    if (!element) return;
    if (!element.matches(":popover-open")) element.showPopover();
    function measure() {
      const box = anchor.current?.getBoundingClientRect();
      if (!box || !element) return;
      const natural = element.scrollHeight + (element.offsetHeight - element.clientHeight);
      const below = window.innerHeight - box.bottom - GAP - EDGE;
      const above = box.top - GAP - EDGE;
      const up = natural > below && above > below;
      const maxHeight = Math.max(140, Math.min(380, up ? above : below));
      const height = Math.min(natural, maxHeight);
      const width = Math.max(element.offsetWidth, match ? box.width : 0);
      const left = align === "end" ? box.right - width : box.left;
      setPlace({
        left: Math.round(Math.max(EDGE, Math.min(left, window.innerWidth - width - EDGE))),
        top: Math.round(up ? box.top - GAP - height : box.bottom + GAP),
        minWidth: match ? Math.round(box.width) : undefined,
        maxHeight,
      });
    }
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [anchor, align, match]);

  useEffect(() => {
    function away(event: PointerEvent) {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !anchor.current?.contains(target)) close.current();
    }
    document.addEventListener("pointerdown", away, true);
    return () => document.removeEventListener("pointerdown", away, true);
  }, [anchor]);

  return (
    <div
      ref={panel}
      popover="manual"
      className={`popover ${className}`}
      style={place ?? { opacity: 0 }}
      onClick={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
    >
      {children}
    </div>
  );
}
