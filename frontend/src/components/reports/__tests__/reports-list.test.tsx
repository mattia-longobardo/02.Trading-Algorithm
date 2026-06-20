import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReportsList } from "@/components/reports/reports-list";
import type { ReportRow } from "@/lib/types";

const REPORT: ReportRow = {
  id: 7,
  filename: "weekly_report_20240101_000000.pdf",
  type: "weekly",
  format: "pdf",
  size_bytes: 2048,
  generated_at: "2024-01-01T00:00:00+00:00",
  folder_id: null,
  tags: "[]",
};

function renderList(isAdmin: boolean) {
  const onDelete = vi.fn();
  render(
    <ReportsList
      items={[REPORT]}
      loading={false}
      folders={[]}
      onPreview={vi.fn()}
      onMove={vi.fn()}
      isAdmin={isAdmin}
      onDelete={onDelete}
    />
  );
  return { onDelete };
}

describe("ReportsList", () => {
  it("shows report deletion only to admins", () => {
    renderList(false);

    expect(
      screen.queryByRole("button", { name: /elimina weekly_report_20240101_000000\.pdf/i })
    ).not.toBeInTheDocument();
  });

  it("calls onDelete when an admin clicks the delete button", async () => {
    const user = userEvent.setup();
    const { onDelete } = renderList(true);

    await user.click(
      screen.getByRole("button", { name: /elimina weekly_report_20240101_000000\.pdf/i })
    );

    expect(onDelete).toHaveBeenCalledWith(REPORT);
  });
});
