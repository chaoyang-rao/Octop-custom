/** Account labels use the current authenticated user, never a directory lookup. */
export function accountDisplayName(user) {
  for (const key of ['display_name', 'username']) {
    const value = user?.[key];
    if (typeof value === 'string' && value.trim()) return value.trim().replace(/\s+/g, ' ');
  }
  return '我';
}

export function initialsFromName(value) {
  const name = typeof value === 'string' ? value.trim() : '';
  if (!name) return '我';
  const han = name.match(/\p{Script=Han}/gu);
  if (han?.length) return han.slice(-2).join('');
  const words = name.match(/\p{Letter}+/gu) || [];
  if (words.length > 1) return (Array.from(words[0])[0] + Array.from(words[words.length - 1])[0]).toUpperCase().slice(0, 2);
  if (words.length === 1) return Array.from(words[0]).slice(0, 2).join('').toUpperCase().slice(0, 2);
  const digits = name.match(/[0-9]/g);
  return digits?.length ? digits.slice(0, 2).join('') : '我';
}

export function accountInitials(user) {
  return initialsFromName(accountDisplayName(user));
}

export function createAccountAvatar({ React }) {
  return function AccountInitialAvatar({ user, className }) {
    const name = accountDisplayName(user);
    return React.createElement('span', {
      className,
      'data-account-initials': '',
      role: 'img',
      'aria-label': name,
      title: name,
      style: {
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        background: 'transparent', color: 'var(--fn-text-primary)', border: 0,
        boxShadow: 'none', fontSize: 13, fontWeight: 650, lineHeight: 1,
        letterSpacing: '.015em', whiteSpace: 'nowrap', flexShrink: 0,
      },
    }, accountInitials(user));
  };
}
