// What a unit of the map is called (the hex trial, docs/hex-trial/README.md).
//
// A riding on the riding sets; whatever the reference set's set.json says on
// any other ("holding" on the hex board). The exporter puts it in the beat
// index (`unit_word`); a Story sets it from there when it is made, and every
// count and card that names the unit reads it here, so no page hard-codes
// either word. A game whose index has none is told in ridings, exactly as
// before.
//
// Pure apart from the one setting, which each Story makes afresh.

export const RIDING = Object.freeze({ singular: 'riding', plural: 'ridings' });

let current = RIDING;

// Use `word` ({singular, plural}) from here on; anything else restores ridings.
export function useUnitWord(word) {
  current = word && word.singular && word.plural
    ? Object.freeze({ singular: String(word.singular), plural: String(word.plural) })
    : RIDING;
  return current;
}

export function unitWord() {
  return current;
}

// "riding" or "ridings" (or the set's words) for a count of n.
export function unitNoun(n = 1) {
  return n === 1 ? current.singular : current.plural;
}

// An engine line in the set's words: "riding" and "ridings" as whole words
// become the set's, keeping a capital. On the riding sets it is the line as
// written.
export function inUnitWords(text) {
  if (current === RIDING || current.singular === RIDING.singular) return text;
  return text.replace(/\b([Rr])iding(s?)\b/g, (_, r, s) => {
    const word = s ? current.plural : current.singular;
    return r === 'R' ? word.charAt(0).toUpperCase() + word.slice(1) : word;
  });
}
