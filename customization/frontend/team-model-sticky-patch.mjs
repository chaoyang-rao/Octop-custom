/**
 * Team rooms: keep the model picked in the composer.
 *
 * A team room creates fresh threads, so the per-thread override is gone on the
 * next round and the picker fell back to Auto. Remember the choice per team
 * agent so the derived state can restore it when the thread has no override.
 */

function once(source, before, after) {
  const count = source.split(before).length - 1;
  if (count !== 1) {
    throw new Error(`Team model patch expected one anchor, found ${count}: ${before.slice(0, 80)}`);
  }
  return source.replace(before, after);
}

const HELPERS =
  'const octopTeamModelKey=id=>`octop.teamModel.${id}`;' +
  'function octopReadTeamModel(id){try{return window.localStorage.getItem(octopTeamModelKey(id))||null}catch(e){return null}}' +
  'function octopWriteTeamModel(id,model){try{const key=octopTeamModelKey(id);model?window.localStorage.setItem(key,model):window.localStorage.removeItem(key)}catch(e){}}';

export function patchTeamModelSticky(source) {
  if (source.includes('octopReadTeamModel')) throw new Error('Team model patch was already applied');
  let out = source;
  const reactImport = 'from"./vendor-react.';
  const importAt = out.indexOf(reactImport);
  if (importAt < 0) throw new Error('React import anchor changed');
  const importEnd = out.indexOf(';', importAt) + 1;
  out = `${out.slice(0, importEnd)}${HELPERS}${out.slice(importEnd)}`;

  out = once(
    out,
    'setSelectedModel(model);const defaults=model?modelReasoning[model]:void 0',
    'setSelectedModel(model),(teamHost&&resolvedAgentId)&&octopWriteTeamModel(resolvedAgentId,model);const defaults=model?modelReasoning[model]:void 0',
  );
  out = once(
    out,
    'setSelectedModel(local?local.model:stickyModel||expertDefaultModel||preferredModel||null)',
    'setSelectedModel(local?local.model:stickyModel||expertDefaultModel||preferredModel||(teamHost&&resolvedAgentId?octopReadTeamModel(resolvedAgentId):null)||null)',
  );
  return out;
}

export function patchTeamModelStickyLocale(source) {
  return source;
}
