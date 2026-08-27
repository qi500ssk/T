"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";

export interface SelectMenuOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectMenuProps {
  value: string;
  options: readonly SelectMenuOption[];
  onChange: (value: string) => void;
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
  name?: string;
  menuMinWidth?: number;
  align?: "start" | "end";
}

interface MenuPosition {
  top?: number;
  bottom?: number;
  left: number;
  width: number;
}

const defaultTriggerClass = "h-11 w-full rounded-xl border border-zinc-300 bg-white px-3 text-sm";

function firstEnabled(options: readonly SelectMenuOption[]) {
  return Math.max(0, options.findIndex((option) => !option.disabled));
}

function nextEnabled(options: readonly SelectMenuOption[], current: number, direction: 1 | -1) {
  if (options.length === 0) return 0;
  for (let step = 1; step <= options.length; step += 1) {
    const index = (current + direction * step + options.length) % options.length;
    if (!options[index]?.disabled) return index;
  }
  return current;
}

export default function SelectMenu({
  value,
  options,
  onChange,
  ariaLabel,
  className = defaultTriggerClass,
  disabled = false,
  name,
  menuMinWidth = 180,
  align = "start",
}: SelectMenuProps) {
  const reactId = useId();
  const listboxId = `${reactId}-listbox`;
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [position, setPosition] = useState<MenuPosition | null>(null);

  const selectedIndex = useMemo(() => options.findIndex((option) => option.value === value), [options, value]);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;

  const updatePosition = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewportGap = 8;
    const menuGap = 7;
    const availableBelow = window.innerHeight - rect.bottom - viewportGap;
    const availableAbove = rect.top - viewportGap;
    const estimatedHeight = Math.min(options.length * 42 + 10, 280);
    const opensUp = availableBelow < Math.min(estimatedHeight, 180) && availableAbove > availableBelow;
    const width = Math.min(Math.max(rect.width, menuMinWidth), window.innerWidth - viewportGap * 2);
    const preferredLeft = align === "end" ? rect.right - width : rect.left;
    const left = Math.min(Math.max(viewportGap, preferredLeft), window.innerWidth - width - viewportGap);

    setPosition(opensUp
      ? { bottom: window.innerHeight - rect.top + menuGap, left, width }
      : { top: rect.bottom + menuGap, left, width });
  };

  const openMenu = (initialIndex = selectedIndex >= 0 ? selectedIndex : firstEnabled(options)) => {
    if (disabled || options.length === 0) return;
    setActiveIndex(options[initialIndex]?.disabled ? firstEnabled(options) : initialIndex);
    setOpen(true);
  };

  const closeMenu = (restoreFocus = false) => {
    setOpen(false);
    setPosition(null);
    if (restoreFocus) requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const choose = (index: number) => {
    const option = options[index];
    if (!option || option.disabled) return;
    onChange(option.value);
    closeMenu(true);
  };

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    const frame = requestAnimationFrame(() => menuRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  // Position is recalculated when the menu opens or its item count changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, options.length]);

  useEffect(() => {
    if (!open) return;
    const reposition = () => updatePosition();
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) closeMenu();
    };
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  // Event listeners only exist while the menu is open.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const base = selectedIndex >= 0 ? selectedIndex : firstEnabled(options);
      openMenu(event.key === "ArrowDown" ? nextEnabled(options, base, 1) : nextEnabled(options, base, -1));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) closeMenu();
      else openMenu();
    }
  };

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => nextEnabled(options, current, event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const index = event.key === "Home"
        ? firstEnabled(options)
        : [...options].map((option, index) => ({ option, index })).reverse().find(({ option }) => !option.disabled)?.index ?? 0;
      setActiveIndex(index);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(activeIndex);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeMenu(true);
    } else if (event.key === "Tab") {
      closeMenu();
    }
  };

  const menuStyle: CSSProperties | undefined = position
    ? { top: position.top, bottom: position.bottom, left: position.left, width: position.width }
    : undefined;

  return (
    <>
      {name && <input type="hidden" name={name} value={value} />}
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled}
        onClick={() => {
          if (open) closeMenu();
          else openMenu();
        }}
        onKeyDown={onTriggerKeyDown}
        className={`group flex min-w-0 items-center justify-between gap-2 text-left outline-none transition duration-150 hover:border-zinc-400 hover:bg-zinc-50 focus-visible:border-zinc-500 focus-visible:ring-4 focus-visible:ring-zinc-100 disabled:cursor-not-allowed disabled:bg-zinc-100 disabled:text-zinc-400 ${className}`}
      >
        <span className="min-w-0 flex-1 truncate">{selected?.label ?? value}</span>
        <svg aria-hidden="true" viewBox="0 0 16 16" className={`size-4 shrink-0 text-zinc-400 transition-transform duration-150 ${open ? "rotate-180 text-zinc-700" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
      {open && typeof document !== "undefined" && createPortal(
        <div
          ref={menuRef}
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          aria-activedescendant={`${listboxId}-option-${activeIndex}`}
          tabIndex={-1}
          onKeyDown={onMenuKeyDown}
          style={menuStyle}
          className={`fixed z-[100] max-h-[17.5rem] overflow-y-auto rounded-2xl border border-zinc-200 bg-white p-1.5 shadow-[0_18px_55px_rgba(24,24,27,0.16)] outline-none transition-opacity ${position ? "opacity-100" : "pointer-events-none opacity-0"}`}
        >
          {options.map((option, index) => {
            const isSelected = option.value === value;
            const isActive = index === activeIndex;
            return (
              <button
                key={option.value}
                id={`${listboxId}-option-${index}`}
                type="button"
                role="option"
                aria-selected={isSelected}
                disabled={option.disabled}
                onPointerMove={() => !option.disabled && setActiveIndex(index)}
                onClick={() => choose(index)}
                className={`flex min-h-10 w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${isActive ? "bg-zinc-100 text-zinc-950" : "text-zinc-700"}`}
              >
                <span className="min-w-0 flex-1 truncate">{option.label}</span>
                <svg aria-hidden="true" viewBox="0 0 16 16" className={`size-4 shrink-0 ${isSelected ? "text-zinc-950" : "invisible"}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m3 8.5 3 3 7-7" />
                </svg>
              </button>
            );
          })}
        </div>,
        document.body,
      )}
    </>
  );
}
