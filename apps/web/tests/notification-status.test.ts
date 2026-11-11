import { describe, expect, it } from "vitest";
import { notificationStatus } from "../app/components/admin/notification-status";

describe("notification presentation", () => {
  it.each([
    ["pending", "awaiting", "Ожидает отправки", ""],
    ["pending", "delayed", "Задержка отправки", "waiting"],
    ["pending", "temporary", "Временная ошибка", "waiting"],
    ["processing", null, "Отправляется", "in_progress"],
    ["processing", "temporary", "Отправляется", "in_progress"],
    ["processing", "delayed", "Отправляется", "in_progress"],
    ["processing", "expired", "Отправляется", "in_progress"],
    ["pending", "expired", "Повторы прекращены", "error"],
    ["failed", "permanent", "Ошибка отправки", "error"],
    ["expired", "expired", "Повторы прекращены", "error"],
    ["sent", null, "Отправлено", "completed"],
    ["cancelled", null, "Отправка отменена", ""],
    ["sent", "temporary", "Отправлено", "completed"],
    ["cancelled", "expired", "Отправка отменена", ""],
  ] as const)(
    "%s with %s is displayed as %s",
    (status, reason, label, tone) => {
      expect(notificationStatus(status, reason)).toEqual({ label, tone });
    },
  );
  it("a queued manual retry after automatic expiry still waits for sending", () => {
    expect(notificationStatus("pending", "expired", true)).toEqual({
      label: "Ожидает отправки",
      tone: "",
    });
  });
});
