export function analyticsConfig(): { counterId: number } | null {
  const id = process.env.YANDEX_METRIKA_ID || "";
  const counterId = Number(id);
  if (
    process.env.NODE_ENV !== "production" ||
    process.env.YANDEX_METRIKA_ENABLED !== "true" ||
    !/^[1-9]\d*$/.test(id) ||
    !Number.isSafeInteger(counterId)
  )
    return null;
  return { counterId };
}
