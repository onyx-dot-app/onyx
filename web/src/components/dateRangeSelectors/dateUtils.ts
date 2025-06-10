export function getXDaysAgo(daysAgo: number) {
  const today = new Date();
  const daysAgoDate = new Date(today);
  daysAgoDate.setDate(today.getDate() - daysAgo);
  return daysAgoDate;
}

export function convertDateToEndOfDay(date?: Date | null) {
  if (!date) {
    return date;
  }

  const dateCopy = new Date(date);
  dateCopy.setHours(23, 59, 59, 999);
  return dateCopy;
}

export function convertDateToStartOfDay(date?: Date | null) {
  if (!date) {
    return date;
  }

  const dateCopy = new Date(date);
  dateCopy.setHours(0, 0, 0, 0);
  return dateCopy;
}
