export function resumeBudget(
  data: Record<string, unknown>,
): 1 | 2 | "MASTER" | null {
  if ([1, 2, "MASTER"].includes(data.page_budget as number | string))
    return data.page_budget as 1 | 2 | "MASTER";
  return data.character_budget === 3500
    ? 1
    : data.character_budget === 7000
      ? 2
      : data.character_budget === 20000
        ? "MASTER"
        : null;
}
export function resumeBudgetLabel(data: Record<string, unknown>): string {
  const budget = resumeBudget(data);
  return budget === "MASTER"
    ? "전체 경력 마스터"
    : budget
      ? `${budget}페이지`
      : "미기록";
}
