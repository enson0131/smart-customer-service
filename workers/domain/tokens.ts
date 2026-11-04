/** 中文连续字符生成二元组，英文和数字按词保留。 */
export function tokens(text: string): string[] {
  const words = text.toLowerCase().match(/[\u3400-\u9fff]+|[a-z0-9]+/g) ?? [];
  return words.flatMap((word) =>
    /^[a-z0-9]+$/.test(word) || word.length === 1
      ? [word]
      : Array.from({ length: word.length - 1 }, (_, i) => word.slice(i, i + 2)),
  );
}
