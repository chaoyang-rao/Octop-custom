/** Read-only host-folder chooser using Octop's authenticated filesystem API. */
const normalize = value => String(value || '').trim().replace(/\\/g, '/');
const pathKey = value => {
  const path = normalize(value).replace(/\/$/, '');
  return /^[a-z]:/i.test(path) || path.startsWith('//') ? path.toLowerCase() : path;
};
const isAbsolute = value => /^(?:\/|[a-z]:\/|~(?:\/|$))/i.test(normalize(value));
const isRoot = value => value === '/' || /^[a-z]:\/$/i.test(value) || /^\/\/[^/]+\/[^/]+\/?$/.test(value);
const within = (value, root) => {
  const key = pathKey(value), base = pathKey(root);
  return key === base || key.startsWith(`${base}/`);
};

function parentPath(value, roots) {
  const path = normalize(value).replace(/\/$/, '');
  if (!path || path === '~' || isRoot(`${path}/`) || roots.some(root => pathKey(root) === pathKey(path))) return null;
  const slash = path.lastIndexOf('/');
  if (slash < 0) return null;
  let parent = path.slice(0, slash) || '/';
  if (/^[a-z]:$/i.test(parent)) parent += '/';
  const bounded = roots.length === 1 && !isRoot(roots[0]);
  return bounded && !within(parent, roots[0]) ? null : parent;
}

export function createProjectFolderPicker({ React, request, Dialog, readableError = error => String(error?.message || error) }) {
  const h = React.createElement;

  return function ProjectFolderPicker({ initialPath = '', onSelect, onClose }) {
    const [roots, setRoots] = React.useState([]);
    const [initialized, setInitialized] = React.useState(false);
    const [draft, setDraft] = React.useState(normalize(initialPath));
    const [listing, setListing] = React.useState({ path: '', entries: [], loading: true, error: '' });
    const alive = React.useRef(true);
    const sequence = React.useRef(0);
    const pending = React.useRef(null);
    const draftRef = React.useRef(normalize(initialPath));

    const close = () => {
      if (!alive.current) return;
      alive.current = false;
      sequence.current++;
      pending.current = null;
      onClose();
    };
    const choose = path => {
      if (!alive.current) return;
      alive.current = false;
      sequence.current++;
      pending.current = null;
      onSelect(path);
    };
    const changeDraft = value => {
      draftRef.current = value;
      setDraft(value);
    };

    const load = async (value, selectAfterLoad = false) => {
      const target = normalize(value);
      if (!alive.current || (pending.current && pathKey(pending.current.path) === pathKey(target))) return;
      if (!isAbsolute(target)) {
        sequence.current++;
        pending.current = null;
        setListing(previous => ({ ...previous, loading: false, error: '请输入文件夹的绝对路径，或使用 ~ 表示主目录。' }));
        return;
      }
      const id = ++sequence.current;
      pending.current = { id, path: target };
      setListing(previous => ({ ...previous, loading: true, error: '' }));
      try {
        const result = await request(`/filesystem/dirs?path=${encodeURIComponent(target)}`);
        if (!alive.current || sequence.current !== id) return;
        const canonical = normalize(result?.path);
        if (!canonical || canonical.startsWith('~') || !isAbsolute(canonical) || !Array.isArray(result.entries)) {
          throw new Error('无法确认文件夹路径，请重新选择。');
        }
        const unchangedDraft = pathKey(draftRef.current) === pathKey(target);
        if (unchangedDraft) changeDraft(canonical);
        setListing({ path: canonical, entries: result.entries, loading: false, error: '' });
        if (selectAfterLoad && unchangedDraft) choose(canonical);
      } catch (error) {
        if (alive.current && sequence.current === id) {
          setListing(previous => ({ ...previous, entries: [], loading: false, error: readableError(error) }));
        }
      } finally {
        if (pending.current?.id === id) pending.current = null;
      }
    };
    const navigate = value => {
      const target = normalize(value);
      changeDraft(target);
      return load(target);
    };
    const initialize = async () => {
      if (!alive.current || pending.current?.path === '@defaults') return;
      const id = ++sequence.current;
      pending.current = { id, path: '@defaults' };
      setListing(previous => ({ ...previous, loading: true, error: '' }));
      try {
        const defaults = await request('/filesystem/defaults');
        if (!alive.current || sequence.current !== id) return;
        const candidates = defaults?.browse_roots?.length ? defaults.browse_roots : [defaults?.tree_root || defaults?.default_root_dir || '/'];
        const nextRoots = [...new Set(candidates.map(normalize).filter(Boolean))];
        setRoots(nextRoots);
        setInitialized(true);
        pending.current = null;
        const initial = normalize(draftRef.current);
        const bounded = nextRoots.length === 1 && !isRoot(nextRoots[0]);
        await navigate(isAbsolute(initial) ? initial : bounded ? nextRoots[0] : '~');
      } catch (error) {
        if (alive.current && sequence.current === id) {
          setListing(previous => ({ ...previous, loading: false, error: readableError(error) }));
        }
      } finally {
        if (pending.current?.id === id) pending.current = null;
      }
    };

    React.useEffect(() => {
      alive.current = true;
      void initialize();
      return () => {
        alive.current = false;
        sequence.current++;
        pending.current = null;
      };
    }, []);

    const confirm = () => {
      if (!alive.current || !initialized || pending.current || listing.loading) return;
      if (!listing.error && listing.path && pathKey(draft) === pathKey(listing.path)) choose(listing.path);
      else void load(draft, true);
    };
    const parent = parentPath(draft, roots);
    const currentRoot = roots.find(root => within(draft, root)) || '';
    const duplicatePending = listing.loading && pending.current && pathKey(pending.current.path) === pathKey(draft);

    return h(Dialog, { title: '选择项目文件夹', busy: false, onClose: close },
      h('div', { className: 'octop-folder-picker', 'data-testid': 'project-folder-picker' },
        h('p', { className: 'octop-project-help' }, '选择 Octop 所在电脑上的项目文件夹。这里只浏览已有文件夹，不会移动文件。'),
        h('div', { className: 'octop-folder-picker-navigation' },
          h('button', { type: 'button', disabled: !initialized || !parent, onClick: () => void navigate(parent), 'aria-label': '上一级文件夹' }, '上一级'),
          h('label', { className: 'octop-folder-picker-roots' }, '位置根目录',
            h('select', { 'aria-label': '位置根目录', value: currentRoot, disabled: !initialized, onChange: event => void navigate(event.target.value) },
              !currentRoot && h('option', { value: '', disabled: true }, '选择根目录'),
              ...roots.map(root => h('option', { key: root, value: root }, root))))),
        h('div', { className: 'octop-folder-picker-location' },
          h('label', null, '文件夹位置', h('input', {
            'aria-label': '文件夹位置', value: draft, spellCheck: false, autoComplete: 'off', autoFocus: true,
            onChange: event => changeDraft(event.target.value),
            onKeyDown: event => {
              if (event.key === 'Enter' && !event.nativeEvent?.isComposing) {
                event.preventDefault(); event.stopPropagation();
                if (initialized) void load(draftRef.current);
              }
            },
          })),
          h('button', { type: 'button', disabled: !initialized || !!duplicatePending, onClick: () => void load(draftRef.current) }, '前往')),
        listing.error && h('div', { className: 'octop-project-error', role: 'alert' }, listing.error,
          h('button', { type: 'button', className: 'octop-folder-picker-retry', onClick: () => void (initialized ? load(draftRef.current) : initialize()) }, '重试')),
        listing.loading ? h('p', { className: 'octop-folder-picker-status', role: 'status' }, '正在读取文件夹…') : !listing.error && h('div', null,
          h('p', { className: 'octop-folder-picker-current' }, '当前文件夹：', h('span', null, listing.path)),
          listing.entries.length ? h('ul', { className: 'octop-folder-picker-list', 'aria-label': '子文件夹' },
            ...listing.entries.map(entry => h('li', { key: entry.path },
              h('button', { type: 'button', title: entry.path, onClick: () => void navigate(entry.path) },
                h('svg', { viewBox: '0 0 24 24', width: 16, height: 16, fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, 'aria-hidden': true },
                  h('path', { d: 'M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z' })),
                h('span', null, entry.name), h('span', { 'aria-hidden': true }, '›'))))) : h('p', { className: 'octop-folder-picker-status' }, '没有子文件夹，可直接选择当前文件夹。')),
        h('div', { className: 'octop-project-dialog-actions' },
          h('button', { type: 'button', onClick: close }, '取消'),
          h('button', { type: 'button', className: 'primary', disabled: !initialized || listing.loading || !normalize(draft), onClick: confirm }, '选择此文件夹'))));
  };
}
