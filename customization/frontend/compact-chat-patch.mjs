/* Pure source patch for the versioned chat chunk; performs no file or DOM I/O. */
export const ORIGINAL_COMPOSER_MINIMUM = "MIN_TEXTAREA_HEIGHT=isMobile?42:78";
export const COMPACT_COMPOSER_MINIMUM = "MIN_TEXTAREA_HEIGHT=isMobile?24:39";

export function patchCompactChatSource(source) {
  if (typeof source !== "string") {
    throw new TypeError("Chat chunk source must be a string");
  }
  const matches = source.split(ORIGINAL_COMPOSER_MINIMUM).length - 1;
  if (matches !== 1) {
    throw new Error(`Expected exactly one original composer minimum, found ${matches}`);
  }
  return source.replace(ORIGINAL_COMPOSER_MINIMUM, COMPACT_COMPOSER_MINIMUM);
}
