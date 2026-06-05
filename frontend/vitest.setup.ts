import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

// cmdk uses ResizeObserver internally; jsdom does not implement it.
if (typeof ResizeObserver === "undefined") {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// cmdk calls scrollIntoView on items when navigating; jsdom does not implement it.
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = function () {};
}

// jsdom does not implement window.matchMedia; next-themes calls it on mount.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// next-themes writes the active theme as a class on <html>; React Testing
// Library's cleanup() unmounts components but never touches documentElement,
// so the class would leak between tests. Reset it before each test to keep
// theme-dependent tests order-independent.
beforeEach(() => {
  document.documentElement.classList.remove("light", "dark");
});

afterEach(() => {
  cleanup();
});
