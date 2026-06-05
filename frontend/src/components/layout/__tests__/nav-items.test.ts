import { describe, it, expect } from "vitest";
import { NAV, visibleNavFor } from "@/components/layout/nav-items";

describe("nav-items", () => {
  it("admins see every nav item", () => {
    expect(visibleNavFor("admin")).toHaveLength(NAV.length);
  });

  it("users do not see admin-only items", () => {
    const adminOnlyCount = NAV.filter((item) => item.adminOnly).length;
    const userNav = visibleNavFor("user");
    expect(userNav).toHaveLength(NAV.length - adminOnlyCount);
    expect(userNav.every((item) => !item.adminOnly)).toBe(true);
  });

  it("every item has a unique href", () => {
    const hrefs = NAV.map((item) => item.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
