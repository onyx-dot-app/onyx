function toCalendarDay(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

// Local calendar days, not UTC ones: toISOString() on a local-midnight Date
// shifts the whole series back a day for users at positive UTC offsets.
// endDate keeps its default for AgentStats, which charts up to "now".
export function getDatesList(startDate: Date, endDate = new Date()): string[] {
  const datesList: string[] = [];

  for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
    datesList.push(toCalendarDay(d));
  }

  return datesList;
}
