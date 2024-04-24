export function getXDaysAgo(daysAgo: number) {
  const today = new Date();
  const daysAgoDate = new Date(today);
  daysAgoDate.setDate(today.getDate() - daysAgo);
  return daysAgoDate;
}

export function getXYearsAgo(yearsAgo: number) {
  const today = new Date();
  const yearsAgoDate = new Date(today);
  yearsAgoDate.setFullYear(yearsAgoDate.getFullYear() - yearsAgo);
  return yearsAgoDate;
}
