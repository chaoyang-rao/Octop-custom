/**
 * Token usage: add a "by project folder" dimension.
 *
 * The dashboard already renders any `by_*` granularity through the generic
 * DimensionView, so the production patch only has to (a) add the view option,
 * (b) title the project column, (c) title the project donut, and (d) localize
 * the three new strings in the shipped locale chunks.
 */

function once(source, before, after) {
  const count = source.split(before).length - 1;
  if (count !== 1) throw new Error(`Token usage project patch expected one anchor, found ${count}: ${before.slice(0, 90)}`);
  return source.replace(before, after);
}

export function patchTokenUsageProject(source) {
  if (source.includes('tokenUsage.byProject')) throw new Error('Token usage project patch was already applied');
  let out = once(source,
    '{value:"by_model",label:t("tokenUsage.byModel")}]',
    '{value:"by_model",label:t("tokenUsage.byModel")},{value:"by_project",label:t("tokenUsage.byProject","项目文件夹")}]');
  out = once(out,
    'function bucketColumnTitle(granularity,t){return t(granularity==="by_day"?"tokenUsage.date":granularity==="by_agent"?"tokenUsage.expert":"tokenUsage.model")}',
    'function bucketColumnTitle(granularity,t){return t(granularity==="by_day"?"tokenUsage.date":granularity==="by_agent"?"tokenUsage.expert":granularity==="by_project"?"tokenUsage.project":"tokenUsage.model")}');
  out = once(out,
    'title:t(granularity==="by_agent"?"tokenUsage.expertBreakdown":"tokenUsage.modelBreakdown")',
    'title:t(granularity==="by_agent"?"tokenUsage.expertBreakdown":granularity==="by_project"?"tokenUsage.projectBreakdown":"tokenUsage.modelBreakdown")');
  return out;
}

const LOCALE_STRINGS = [
  { anchor: 'byModel:"按模型",', insert: 'byProject:"按项目",project:"项目",projectBreakdown:"项目分布",' },
  { anchor: 'byModel:"By model",', insert: 'byProject:"By project",project:"Project",projectBreakdown:"By project",' },
];

export function patchTokenUsageProjectLocale(source) {
  if (source.includes('byProject')) throw new Error('Token usage locale patch was already applied');
  const entry = LOCALE_STRINGS.find(candidate => source.includes(candidate.anchor));
  if (!entry) throw new Error('Token usage locale chunk is not recognized');
  return once(source, entry.anchor, entry.anchor + entry.insert);
}

/** Summary view: add the project donut next to the input/output, expert and model pies. */
export function patchTokenUsageSummaryProject(source) {
  if (source.includes('summaryProject')) throw new Error('Token usage summary project patch was already applied');
  let out = once(source,
    '[summaryModel,setSummaryModel]=reactExports.useState([])',
    '[summaryModel,setSummaryModel]=reactExports.useState([]),[summaryProject,setSummaryProject]=reactExports.useState([])');
  out = once(out,
    'const[expertRes,modelRes,dayRes]=await Promise.all([fetchSummary(windowKey,"by_agent",agentFilter,adminUserFilter),fetchSummary(windowKey,"by_model",agentFilter,adminUserFilter),fetchSummary(windowKey,"by_day",agentFilter,adminUserFilter)]);',
    'const[expertRes,modelRes,dayRes,projectRes]=await Promise.all([fetchSummary(windowKey,"by_agent",agentFilter,adminUserFilter),fetchSummary(windowKey,"by_model",agentFilter,adminUserFilter),fetchSummary(windowKey,"by_day",agentFilter,adminUserFilter),fetchSummary(windowKey,"by_project",agentFilter,adminUserFilter)]);');
  out = once(out, 'setSummaryDay(dayRes.buckets),setDimBuckets([])', 'setSummaryDay(dayRes.buckets),setSummaryProject(projectRes.buckets),setDimBuckets([])');
  out = once(out, 'function SummaryView({totals,byExpert,byModel,byDay,isMobile})', 'function SummaryView({totals,byExpert,byModel,byProject,byDay,isMobile})');
  out = once(out, 'modelPie=reactExports.useMemo(()=>toPieData(byModel),[byModel])',
    'modelPie=reactExports.useMemo(()=>toPieData(byModel),[byModel]),projectPie=reactExports.useMemo(()=>toPieData(byProject),[byProject])');
  out = once(out, 'gridTemplateColumns:isMobile?"1fr":"repeat(3, minmax(0, 1fr))"', 'gridTemplateColumns:isMobile?"1fr":"repeat(4, minmax(0, 1fr))"');
  out = once(out,
    'jsxRuntimeExports.jsx(DonutCard,{title:t("tokenUsage.modelBreakdown"),data:modelPie,emptyText:t("tokenUsage.noRecordsInRange")})',
    'jsxRuntimeExports.jsx(DonutCard,{title:t("tokenUsage.modelBreakdown"),data:modelPie,emptyText:t("tokenUsage.noRecordsInRange")}),jsxRuntimeExports.jsx(DonutCard,{title:t("tokenUsage.projectBreakdown"),data:projectPie,emptyText:t("tokenUsage.noRecordsInRange")})');
  out = once(out,
    'jsxRuntimeExports.jsx(SummaryView,{totals,byExpert:summaryExpert,byModel:summaryModel,byDay:summaryDay,isMobile}',
    'jsxRuntimeExports.jsx(SummaryView,{totals,byExpert:summaryExpert,byModel:summaryModel,byProject:summaryProject,byDay:summaryDay,isMobile}');
  return out;
}

/** Detail card (one layer outside the table): clip the grid so it cannot bleed past the card. */
export function patchTokenUsageDetailCard(source) {
  if (source.includes('octop-token-detail')) throw new Error('Token usage detail card patch was already applied');
  return once(source, 'className:`${styles.chartCard} ${styles.dimTableCard}`',
    'className:`${styles.chartCard} ${styles.dimTableCard} octop-token-detail`');
}
