export type DraftField = {
  type: string;
  name: string;
  id: string;
  value: string;
};
export type DraftPayload = Record<string, { value: string; kind: string }>;
export function draftHasChanges(
  current: DraftPayload,
  baseline: DraftPayload,
  defaults: DraftPayload,
): boolean {
  return Object.entries(current).some(([key, field]) => {
    const original = baseline[key] || defaults[key];
    return (
      !original ||
      field.value !== original.value ||
      field.kind !== original.kind
    );
  });
}
export function editableDraftFields<T extends DraftField>(fields: T[]): T[] {
  const allowed = new Set([
    "text",
    "textarea",
    "number",
    "select-one",
    "select-multiple",
    "email",
    "url",
    "search",
    "date",
    "month",
    "datetime-local",
    "time",
    "tel",
  ]);
  return fields.filter(
    (field) =>
      allowed.has(field.type) &&
      !/(password|token|api_?key|confirm|approval|consent)/i.test(
        field.name || field.id,
      ),
  );
}
export function serializeDraftFields(fields: DraftField[]): DraftPayload {
  return Object.fromEntries(
    editableDraftFields(fields).map((field, index) => [
      `${index}:${field.name || field.id}`,
      { value: field.value, kind: field.type },
    ]),
  );
}
