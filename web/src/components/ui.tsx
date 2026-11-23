import { type ReactNode, useEffect, useRef, useState } from "react";

import { linkTo } from "../router";
import { Icon, type IconName } from "./icons";
import { SplitFlap } from "./instrument";
import { Popover } from "./popover";

export function PageHead({
  title,
  meta,
  tabs,
  children,
}: {
  title: ReactNode;
  meta?: ReactNode;
  tabs?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-title">
        {typeof title === "string" ? <h1>{title}</h1> : title}
        {meta ? <p>{meta}</p> : null}
      </div>
      {tabs}
      {children ? <div className="page-actions">{children}</div> : null}
    </header>
  );
}

/** Secondary navigation inside a page. Each tab is a real address. */
export function Tabs({ label, items, current }: { label: string; items: { to: string; label: string }[]; current: string }) {
  return (
    <nav className="seg tabs" aria-label={label}>
      {items.map((item) => (
        <a key={item.to} {...linkTo(item.to)} aria-current={item.to === current ? "page" : undefined}>
          {item.label}
        </a>
      ))}
    </nav>
  );
}

export function Card({
  title,
  hint,
  actions,
  children,
  className = "",
  id,
}: {
  title: string;
  /** A figure that sums the card up. */
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`card ${className}`} aria-label={title} id={id}>
      <div className="card-head">
        <h2>
          <span className="led-dot" aria-hidden="true" />
          {title}
        </h2>
        {hint ? <span className="hint">{hint}</span> : null}
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ScopeSwitch({ value, onChange }: { value: "everyday" | "all"; onChange: (value: "everyday" | "all") => void }) {
  return (
    <Segmented
      label="Which spending"
      value={value}
      onChange={onChange}
      options={[
        { value: "everyday", label: "Everyday" },
        { value: "all", label: "Everything" },
      ]}
    />
  );
}

/** ◀ LABEL ▶ with a split-flap label: used to step through months and school terms. */
export function Stepper({
  label,
  heading = false,
  onPrevious,
  onNext,
  canPrevious,
  canNext,
  name,
}: {
  label: string;
  /** The label is the page's title. */
  heading?: boolean;
  onPrevious: () => void;
  onNext: () => void;
  canPrevious: boolean;
  canNext: boolean;
  name: string;
}) {
  const flap = <SplitFlap text={label} />;
  return (
    <div className="stepper" role="group" aria-label={name}>
      <button type="button" className="step" onClick={onPrevious} disabled={!canPrevious} aria-label={`Previous ${name}`}>
        <Icon name="left" />
      </button>
      {heading ? <h1>{flap}</h1> : flap}
      <button type="button" className="step" onClick={onNext} disabled={!canNext} aria-label={`Next ${name}`}>
        <Icon name="right" />
      </button>
    </div>
  );
}

export function Fold({ title, children, open }: { title: ReactNode; children: ReactNode; open?: boolean }) {
  return (
    <details className="fold" open={open}>
      <summary>{title}</summary>
      <div className="stack">{children}</div>
    </details>
  );
}

export interface MenuItem {
  label: string;
  icon: IconName;
  danger?: boolean;
  run?: () => void;
  /** A link instead of an action. */
  href?: string;
  download?: boolean;
}

/** A ⋯ button that opens a short list of actions. */
export function Menu({ label, items, small = true }: { label: string; items: MenuItem[]; small?: boolean }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) list.current?.querySelector<HTMLElement>("[role='menuitem']")?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`btn ghost icon ${small ? "small" : ""}`}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((current) => !current);
        }}
      >
        <Icon name="more" size={16} />
      </button>
      {open ? (
        <Popover anchor={button} onClose={() => setOpen(false)} align="end">
          <div
            ref={list}
            className="options"
            role="menu"
            aria-label={label}
            onKeyDown={(event) => {
              event.stopPropagation();
              const all = [...(list.current?.querySelectorAll<HTMLElement>("[role='menuitem']") ?? [])];
              const at = all.indexOf(document.activeElement as HTMLElement);
              if (event.key === "Escape") close();
              else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                const step = event.key === "ArrowDown" ? 1 : -1;
                all[(at + step + all.length) % all.length]?.focus();
              } else if (event.key === "Tab") setOpen(false);
            }}
          >
            {items.map((item) => {
              const content = (
                <>
                  <Icon name={item.icon} />
                  {item.label}
                </>
              );
              const className = `option ${item.danger ? "danger" : ""}`;
              if (item.href) {
                return (
                  <a
                    key={item.label}
                    role="menuitem"
                    className={className}
                    {...(item.download ? { href: item.href, download: true, onClick: close } : linkTo(item.href))}
                  >
                    {content}
                  </a>
                );
              }
              return (
                <button
                  key={item.label}
                  type="button"
                  role="menuitem"
                  className={className}
                  onClick={() => {
                    close();
                    item.run?.();
                  }}
                >
                  {content}
                </button>
              );
            })}
          </div>
        </Popover>
      ) : null}
    </>
  );
}

/** The reason behind an answer, spelled out only when its ? key (or its `lamp`) is pressed. */
export function Info({ label, lamp, children }: { label: string; lamp?: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={button}
        type="button"
        className={lamp ? "lamp-key" : "btn ghost icon small"}
        aria-label={`Why: ${label}`}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) {
            event.stopPropagation();
            setOpen(false);
          }
        }}
      >
        {lamp ?? <Icon name="help" size={16} />}
      </button>
      {open ? (
        <Popover anchor={button} onClose={() => setOpen(false)} align={lamp ? "start" : "end"}>
          <div className="info" role="status">
            {children}
          </div>
        </Popover>
      ) : null}
    </>
  );
}

const MARK = { up: "▲", warn: "!", ok: "✓", info: "●" } as const;

export function Notice({
  tone,
  children,
  action,
  role,
}: {
  tone: keyof typeof MARK;
  children: ReactNode;
  action?: ReactNode;
  role?: string;
}) {
  return (
    <div className={`signal ${tone}`} role={role}>
      <span className="mark" aria-hidden="true">
        {MARK[tone]}
      </span>
      <span className="grow">{children}</span>
      {action}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card empty">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

/** A strip of segments chasing along; appears only if loading takes long enough to notice. */
export function Loading() {
  return (
    <div className="card loading" role="status" aria-label="Loading">
      <span className="segments" aria-hidden="true">
        {Array.from({ length: 24 }, (_, index) => (
          <span key={index} className="segment" style={{ animationDelay: `${index * 60}ms` }} />
        ))}
      </span>
    </div>
  );
}

export function LoadError({ what, error, retry }: { what: string; error: unknown; retry: () => void }) {
  return (
    <Empty title={`Couldn't load ${what}`}>
      <p>{error instanceof Error ? error.message : "The app's server may have stopped."}</p>
      <button type="button" className="btn" onClick={retry}>
        Try again
      </button>
    </Empty>
  );
}
