const labels = {
  open: "申请中", upcoming: "未开放", rolling: "滚动录取", closed: "已截止", unknown: "待确认",
  international_allowed: "国际生可申请", us_only: "仅美国学生", local_only: "地区限制"
};
const correctionBase = "https://github.com/ccl24/summer-school-tracker/issues/new?template=correction.yml";

const state = { programs: [], filters: { search: "", university: "all", status: "all", eligibility: "all", sort: "deadline" } };
const $ = (selector, root = document) => root.querySelector(selector);

function dateText(item) {
  if (!item?.date) return "官方页面未公布";
  const base = new Intl.DateTimeFormat("zh-CN", { dateStyle: "long", timeZone: "UTC" }).format(new Date(`${item.date}T00:00:00Z`));
  let text = `${base}${item.time ? ` ${item.time} ${item.timezone || ""}` : item.timezone ? `（${item.timezone}）` : ""}`;
  if (item.time && item.timezone === "ET") {
    const offset = item.timezone === "ET" ? "-04:00" : "Z";
    const local = new Date(`${item.date}T${item.time}:00${offset}`);
    text += ` · 本地 ${new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(local)}`;
  }
  return text;
}

function relativeChecked(value) {
  if (!value) return "尚未核验";
  return `核验：${new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))}`;
}

function nextDeadline(program) { return program.deadlines?.filter((item) => item.date).sort((a, b) => a.date.localeCompare(b.date))[0] || null; }
function formatEligibility(program) { return labels[program.eligibility] || "资格待确认"; }
function correctionUrl(program) {
  const query = new URLSearchParams({
    title: `[correction] ${program.programName}`,
    "program-id": program.id,
    "program-name": program.programName,
    "official-url": program.sourceUrl || program.programUrl || ""
  });
  return `${correctionBase}&${query.toString()}`;
}

function render() {
  const { search, university, status, eligibility, sort } = state.filters;
  const needle = search.trim().toLocaleLowerCase();
  const visible = state.programs.filter((program) => {
    const searchable = `${program.university} ${program.programName} ${program.eligibilityNote}`.toLocaleLowerCase();
    return (!needle || searchable.includes(needle)) && (university === "all" || program.university === university) && (status === "all" || program.status === status) && (eligibility === "all" || program.eligibility === eligibility);
  }).sort((a, b) => {
    if (sort === "university") return a.university.localeCompare(b.university);
    if (sort === "checked") return (b.lastCheckedAt || "").localeCompare(a.lastCheckedAt || "");
    return (nextDeadline(a)?.date || "9999-12-31").localeCompare(nextDeadline(b)?.date || "9999-12-31");
  });
  $("#result-count").textContent = `显示 ${visible.length} / ${state.programs.length} 个项目`;
  const container = $("#programs"); container.replaceChildren();
  if (!visible.length) { container.innerHTML = '<p class="empty">没有符合筛选条件的项目。</p>'; return; }
  const template = $("#program-template");
  visible.forEach((program) => {
    const node = template.content.cloneNode(true);
    $(".university", node).textContent = program.university;
    const pill = $(".status-pill", node); pill.textContent = program.reviewState === "needs_review" ? "待复核" : (labels[program.status] || "待确认"); pill.classList.add(`status-${program.reviewState === "needs_review" ? "unknown" : program.status || "unknown"}`);
    $("h2", node).textContent = program.programName;
    const tags = $(".tags", node); tags.innerHTML = `<span class="tag">${formatEligibility(program)}</span>${program.operator ? `<span class="tag">${program.operator}</span>` : ""}${program.cycleYear ? `<span class="tag">${program.cycleYear} 申请周期</span>` : ""}<span class="tag">${program.dataOrigin === "manual" ? "人工核验" : "自动核验"}</span>${program.reviewState === "needs_review" ? '<span class="tag">数据待复核</span>' : ""}`;
    const dates = $(".dates", node);
    const rows = [];
    rows.push(["申请开放", dateText(program.applicationOpenDate)]);
    (program.deadlines || []).forEach((deadline) => rows.push([deadline.type, `${dateText(deadline)}${deadline.audience ? `<span class="raw">${deadline.audience}</span>` : ""}`]));
    if (!program.deadlines?.length) rows.push(["申请截止", "官方页面未公布具体日期"]);
    if (program.status === "closed" && program.cycleYear && program.cycleYear <= new Date().getFullYear()) rows.push(["下一周期", "官方尚未发布下一年度日期"]);
    dates.innerHTML = rows.map(([term, value]) => `<div><dt>${term}</dt><dd>${value}</dd></div>`).join("");
    const eligibilityNote = $(".eligibility-note", node); eligibilityNote.textContent = program.eligibilityNote || "请查看官方页面确认申请资格。";
    const link = $(".source-link", node); link.href = program.sourceUrl || program.programUrl;
    $(".correction-link", node).href = correctionUrl(program);
    $(".checked-at", node).textContent = relativeChecked(program.lastCheckedAt);
    container.append(node);
  });
}

function bindFilters() {
  [["#search", "search"], ["#university-filter", "university"], ["#status-filter", "status"], ["#eligibility-filter", "eligibility"], ["#sort-filter", "sort"]].forEach(([selector, key]) => {
    $(selector).addEventListener(key === "search" ? "input" : "change", (event) => { state.filters[key] = event.target.value; render(); });
  });
}

async function init() {
  try {
    const response = await fetch("data/programs.json", { cache: "no-store" });
    if (!response.ok) throw new Error("data unavailable");
    const document = await response.json(); state.programs = document.programs || [];
    const universities = [...new Set(state.programs.map((program) => program.university))].sort();
    $("#university-filter").insertAdjacentHTML("beforeend", universities.map((name) => `<option value="${name}">${name}</option>`).join(""));
    $("#updated-at").textContent = `数据最近检查：${new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(document.generatedAt))}`;
    const ageHours = (Date.now() - new Date(document.generatedAt).getTime()) / 36e5;
    if (ageHours > 36) { const banner = $("#stale-banner"); banner.hidden = false; banner.textContent = "数据超过 36 小时未成功更新。请直接查看官方页面确认。"; }
    bindFilters(); render();
  } catch (error) { $("#updated-at").textContent = "无法加载项目数据"; $("#programs").innerHTML = '<p class="empty">项目数据暂时不可用，请稍后再试。</p>'; }
}
init();
