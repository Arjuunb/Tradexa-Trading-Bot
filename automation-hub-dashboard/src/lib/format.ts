// Shared number formatting.
//
// `signedMoney` / `signedNum` always carry a leading +/− so a gain vs. a loss
// never depends on colour alone. The green/red `.pos`/`.neg` classes stay, but
// the sign gives the same meaning to colour-blind users and to screen readers
// (which announce "minus"/"plus"), satisfying WCAG "don't rely on colour".

export const signedMoney = (n: number | null | undefined): string => {
  const v = n ?? 0;
  const abs = Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return `${v >= 0 ? "+" : "−"}$${abs}`;
};

export const signedNum = (n: number | null | undefined, digits = 2): string => {
  const v = n ?? 0;
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}`;
};
