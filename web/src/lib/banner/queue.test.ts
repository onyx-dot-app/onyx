import { buildBannerQueue } from "@/lib/banner/queue";
import {
  NotificationSeverity,
  NotificationType,
  type Notification,
} from "@/lib/notifications/interfaces";

let nextId = 1;

function makeNotification(overrides: Partial<Notification>): Notification {
  return {
    id: nextId++,
    notif_type: NotificationType.LICENSE_EXPIRY_WARNING,
    severity: NotificationSeverity.WARNING,
    title: "test",
    description: null,
    dismissed: false,
    first_shown: "2026-08-01T00:00:00Z",
    last_shown: "2026-08-01T00:00:00Z",
    additional_data: null,
    ...overrides,
  };
}

const neverHidden = () => false;

describe("buildBannerQueue", () => {
  it("orders slots by severity, then recency", () => {
    const older = makeNotification({
      notif_type: NotificationType.SYSTEM_ANNOUNCEMENT,
      severity: NotificationSeverity.WARNING,
      last_shown: "2026-08-01T00:00:00Z",
    });
    const newer = makeNotification({
      notif_type: NotificationType.TRIAL_ENDS_TWO_DAYS,
      severity: NotificationSeverity.WARNING,
      last_shown: "2026-08-02T00:00:00Z",
    });
    const error = makeNotification({
      notif_type: NotificationType.CONNECTOR_REPEATED_ERRORS,
      severity: NotificationSeverity.ERROR,
      last_shown: "2026-07-01T00:00:00Z",
    });

    const queue = buildBannerQueue([older, newer, error], neverHidden);

    expect(queue.map((item) => item.notification.id)).toEqual([
      error.id,
      newer.id,
      older.id,
    ]);
  });

  it("collapses same-type notifications into one slot led by the most urgent", () => {
    const warning = makeNotification({
      severity: NotificationSeverity.WARNING,
      last_shown: "2026-08-02T00:00:00Z",
    });
    const error = makeNotification({
      severity: NotificationSeverity.ERROR,
      last_shown: "2026-08-01T00:00:00Z",
    });

    const queue = buildBannerQueue([warning, error], neverHidden);

    expect(queue).toHaveLength(1);
    expect(queue[0]!.notification.id).toBe(error.id);
    expect(queue[0]!.count).toBe(2);
    expect(queue[0]!.ids).toEqual([error.id, warning.id]);
  });

  it("excludes hidden notifications entirely", () => {
    const visible = makeNotification({});
    const hidden = makeNotification({ dismissed: true });

    const queue = buildBannerQueue(
      [visible, hidden],
      (notification) => notification.dismissed
    );

    expect(queue).toHaveLength(1);
    expect(queue[0]!.ids).toEqual([visible.id]);
  });
});
