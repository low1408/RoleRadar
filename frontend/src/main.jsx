import React from "react";
import { createRoot } from "react-dom/client";
import { Chart } from "chart.js/auto";
import {
  Activity,
  BarChart3,
  BriefcaseBusiness,
  Building2,
  Database,
  Download,
  Gauge,
  Loader2,
  Moon,
  Play,
  Search,
  ShieldCheck,
  Sun,
  Trash2,
  TrendingUp,
  X,
} from "lucide-react";
import "./styles.css";

const api = async (path, options) => {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : null;
  if (!response.ok) {
    throw new Error(body?.detail || `${response.status} ${response.statusText}`);
  }
  return body;
};

const navItems = [
  { href: "#/overview", label: "Overview", icon: BarChart3 },
  { href: "#/explorer", label: "Explorer", icon: Gauge },
  { href: "#/trends", label: "Trends", icon: TrendingUp },
  { href: "#/jobs", label: "Evidence", icon: BriefcaseBusiness },
  { href: "#/load", label: "Load Sources", icon: Database },
  { href: "#/admin", label: "Admin", icon: ShieldCheck },
];

const sourceOptions = [
  { value: "all", label: "All query-capable sources" },
  { value: "careers_gov", label: "MyCareersFuture" },
  { value: "jobstreet", label: "JobStreet" },
  { value: "adzuna", label: "Adzuna" },
];

const customRoleFamilyPrefix = "custom:";
const customRoleFamilyAcronyms = new Map([
  ["ai", "AI"],
  ["api", "API"],
  ["bi", "BI"],
  ["crm", "CRM"],
  ["devops", "DevOps"],
  ["llm", "LLM"],
  ["ml", "ML"],
  ["nlp", "NLP"],
  ["qa", "QA"],
  ["sre", "SRE"],
  ["ui", "UI"],
  ["ux", "UX"],
]);

function App() {
  const [route, setRoute] = React.useState(window.location.hash || "#/overview");
  const [query, setQuery] = React.useState("");
  const [roleFamily, setRoleFamily] = React.useState("");
  const [overviewRoleFamily, setOverviewRoleFamily] = React.useState("");
  const [trendRoleFamily, setTrendRoleFamily] = React.useState("");
  const [trendSkill, setTrendSkill] = React.useState("");
  const [trendWeeks, setTrendWeeks] = React.useState(12);
  const [roleFamilies, setRoleFamilies] = React.useState([]);
  const [payload, setPayload] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [dark, setDark] = React.useState(
    window.localStorage.getItem("roleradar.theme") === "dark",
  );
  const [refreshCounter, setRefreshCounter] = React.useState(0);
  const [toasts, setToasts] = React.useState([]);

  const showToast = (message, actionLabel = null, onAction = null) => {
    const id = Math.random().toString(36).substring(2, 9);
    const toast = { id, message, actionLabel, onAction };
    setToasts((prev) => [...prev, toast]);
    setTimeout(() => {
      dismissToast(id);
    }, 6000);
  };

  const dismissToast = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const handleDeleteListing = async (item) => {
    try {
      await api(`/api/v1/jobs/${item.source_listing_id}`, { method: "DELETE" });
      setRefreshCounter((prev) => prev + 1);
      if (selected && selected.source_listing_id === item.source_listing_id) {
        setSelected(null);
      }
      showToast(
        `Deleted listing "${item.title}" at "${item.company_name}".`,
        "Undo",
        async () => {
          try {
            await api(`/api/v1/jobs/${item.source_listing_id}/restore`, { method: "POST" });
            setRefreshCounter((prev) => prev + 1);
            showToast("Restored listing successfully.");
          } catch (err) {
            showToast(`Failed to restore: ${err.message}`);
          }
        }
      );
    } catch (err) {
      showToast(`Failed to delete: ${err.message}`);
    }
  };
  const routeSection = getRouteSection(route);
  const payloadKey = getPayloadKey(
    routeSection,
    query,
    roleFamily,
    overviewRoleFamily,
    trendRoleFamily,
    trendSkill,
    trendWeeks,
  );
  const viewPayload =
    payload?.routeSection === routeSection && payload?.key === payloadKey
      ? payload.response
      : null;

  React.useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash || "#/overview");
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  React.useEffect(() => {
    document.body.classList.toggle("dark", dark);
    window.localStorage.setItem("roleradar.theme", dark ? "dark" : "light");
  }, [dark]);

  React.useEffect(() => {
    if (
      !route.startsWith("#/jobs") &&
      !route.startsWith("#/overview") &&
      !route.startsWith("#/explorer") &&
      !route.startsWith("#/trends") &&
      !route.startsWith("#/load")
    ) {
      return;
    }
    let isCurrent = true;
    const controller = new AbortController();

    const includeEmpty = route.startsWith("#/load") ? "&include_empty=true" : "";
    api(`/api/v1/role-families?limit=100${includeEmpty}`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (isCurrent) setRoleFamilies(response.data.items || []);
      })
      .catch((err) => {
        if (isCurrent && err.name !== "AbortError") setRoleFamilies([]);
      });

    return () => {
      isCurrent = false;
      controller.abort();
    };
  }, [route, viewPayload?.meta?.freshness_timestamp]);

  React.useEffect(() => {
    let isCurrent = true;
    const controller = new AbortController();

    setError(null);
    setPayload(null);

    if (route.startsWith("#/load")) {
      return () => {
        isCurrent = false;
        controller.abort();
      };
    }

    const params = new URLSearchParams();
    if (query && route.startsWith("#/jobs")) {
      params.set("q", query);
    }
    if (roleFamily && route.startsWith("#/jobs")) {
      params.set("role_family", roleFamily);
    }

    const overviewParams = new URLSearchParams();
    if (overviewRoleFamily && routeSection === "overview") {
      overviewParams.set("role_family", overviewRoleFamily);
    }

    const trendParams = new URLSearchParams();
    trendParams.set("weeks", String(trendWeeks));
    if (trendRoleFamily && routeSection === "trends") {
      trendParams.set("role_family", trendRoleFamily);
    }
    if (trendSkill && routeSection === "trends") {
      trendParams.set("skill", trendSkill);
    }

    const endpoint = route.startsWith("#/jobs")
      ? `/api/v1/jobs?limit=50&${params.toString()}`
      : route.startsWith("#/admin")
        ? "/api/v1/admin/duplicates?limit=50"
        : route.startsWith("#/trends")
          ? `/api/v1/analytics/trends?${trendParams.toString()}`
          : `/api/v1/analytics/overview${
              overviewParams.toString() ? `?${overviewParams.toString()}` : ""
            }`;

    api(endpoint, { signal: controller.signal })
      .then((response) => {
        if (isCurrent) setPayload({ routeSection, key: payloadKey, response });
      })
      .catch((err) => {
        if (isCurrent && err.name !== "AbortError") setError(err.message);
      });

    return () => {
      isCurrent = false;
      controller.abort();
    };
  }, [
    route,
    routeSection,
    payloadKey,
    query,
    roleFamily,
    overviewRoleFamily,
    trendRoleFamily,
    trendSkill,
    trendWeeks,
    refreshCounter,
  ]);

  const isLoadRoute = route.startsWith("#/load");

  return (
    <div className={selected ? "app-shell inspector-open" : "app-shell"}>
      <Sidebar
        route={route}
        query={query}
        setQuery={setQuery}
        dark={dark}
        setDark={setDark}
      />
      <main className="workspace">
        {error && <div className="notice error">{error}</div>}
        {!isLoadRoute && !viewPayload && !error && <LoadingState />}
          {isLoadRoute && (
            <LoadSourcesView setQuery={setQuery} roleFamilies={roleFamilies} />
          )}
        {viewPayload && route.startsWith("#/jobs") && (
          <JobsView
            payload={viewPayload}
            setSelected={setSelected}
            query={query}
            roleFamily={roleFamily}
            setRoleFamily={setRoleFamily}
            roleFamilies={roleFamilies}
            onDelete={handleDeleteListing}
          />
        )}
        {viewPayload && route.startsWith("#/admin") && (
          <AdminView
            payload={viewPayload}
            setPayload={(response) =>
              setPayload({ routeSection, key: payloadKey, response })
            }
            setSelected={setSelected}
            refreshCounter={refreshCounter}
            setRefreshCounter={setRefreshCounter}
            showToast={showToast}
          />
        )}
        {viewPayload && route.startsWith("#/trends") && (
          <TrendsView
            payload={viewPayload}
            roleFamilies={roleFamilies}
            trendRoleFamily={trendRoleFamily}
            setTrendRoleFamily={setTrendRoleFamily}
            trendSkill={trendSkill}
            setTrendSkill={setTrendSkill}
            trendWeeks={trendWeeks}
            setTrendWeeks={setTrendWeeks}
            setSelected={setSelected}
          />
        )}
        {viewPayload &&
          !isLoadRoute &&
          !route.startsWith("#/jobs") &&
          !route.startsWith("#/trends") &&
          !route.startsWith("#/admin") && (
            <OverviewView
              payload={viewPayload}
              route={route}
              setSelected={setSelected}
              selectedRoleFamily={overviewRoleFamily}
              setSelectedRoleFamily={setOverviewRoleFamily}
            />
          )}
      </main>
      <Inspector selected={selected} setSelected={setSelected} />
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

function Sidebar({ route, query, setQuery, dark, setDark }) {
  return (
    <aside className="sidebar">
      <div className="brand-lockup">
        <div className="brand-mark">
          <Activity size={20} strokeWidth={2.3} />
        </div>
        <div>
          <div className="brand">RoleRadar</div>
          <div className="brand-subtitle">SG labour signals</div>
        </div>
      </div>

      <nav className="nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <a
              href={item.href}
              className={route.startsWith(item.href) ? "active" : ""}
              key={item.href}
            >
              <Icon size={17} />
              <span>{item.label}</span>
            </a>
          );
        })}
      </nav>

      <div className="sidebar-section">
        <div className="section-label">Global Search</div>
        <label className="search-box">
          <Search size={16} />
          <input
            value={query}
            onInput={(event) => setQuery(event.target.value)}
            placeholder="role, company, skill"
          />
        </label>
      </div>

      <div className="sidebar-footer">
        <button className="utility-button" onClick={() => setDark(!dark)}>
          {dark ? <Sun size={16} /> : <Moon size={16} />}
          <span>{dark ? "Light mode" : "Dark mode"}</span>
        </button>
      </div>
    </aside>
  );
}

function LoadSourcesView({ setQuery, roleFamilies }) {
  const [source, setSource] = React.useState("careers_gov");
  const [role, setRole] = React.useState("AI engineer");
  const [roleFamily, setRoleFamily] = React.useState("");
  const [roleFamilyMode, setRoleFamilyMode] = React.useState("catalog");
  const [customRoleFamily, setCustomRoleFamily] = React.useState("");
  const [location, setLocation] = React.useState("Singapore");
  const [resultsPerPage, setResultsPerPage] = React.useState(20);
  const [maxPages, setMaxPages] = React.useState(1);
  const [result, setResult] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const resultRoleFamily = result
    ? roleFamilies.find((item) => item.id === result.data.role_family)
    : null;
  const selectedRoleFamilyId =
    roleFamilyMode === "custom"
      ? customRoleFamilyId(customRoleFamily)
      : roleFamily;
  const selectedRoleFamilyLabel =
    roleFamilyMode === "custom"
      ? normalizeCustomRoleFamilyLabel(customRoleFamily)
      : roleFamilies.find((item) => item.id === roleFamily)?.label;
  const canSubmit = Boolean(selectedRoleFamilyId);

  const submitLoad = async (event) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    setIsLoading(true);

    try {
      const response = await api("/api/v1/admin/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source,
          query: role,
          role_family: selectedRoleFamilyId,
          location,
          results_per_page: Number(resultsPerPage),
          max_pages: Number(maxPages),
        }),
      });
      setQuery(role);
      setResult(response);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Source Loader"
        title="Load role listings from job sources"
        meta="Search-driven ingestion"
      />

      <section className="load-grid">
        <form className="panel load-form" onSubmit={submitLoad}>
          <PanelHeader
            title="Load From Sources"
            subtitle="Choose a source, role query, canonical family, and page depth."
          />

          <div className="field-grid">
            <label className="field-control">
              <span>Source</span>
              <select
                value={source}
                onChange={(event) => setSource(event.target.value)}
              >
                {sourceOptions.map((option) => (
                  <option value={option.value} key={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field-control">
              <span>Role query</span>
              <input
                value={role}
                onInput={(event) => setRole(event.target.value)}
                placeholder="AI engineer"
                required
              />
            </label>

            <label className="field-control">
              <span>Canonical role family</span>
              <select
                value={roleFamily}
                onChange={(event) => setRoleFamily(event.target.value)}
                disabled={roleFamilyMode === "custom"}
                required={roleFamilyMode === "catalog"}
              >
                <option value="">Select a role family</option>
                {roleFamilies.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="toggle-control">
              <input
                type="checkbox"
                checked={roleFamilyMode === "custom"}
                onChange={(event) =>
                  setRoleFamilyMode(event.target.checked ? "custom" : "catalog")
                }
              />
              <span>Define my own canonical role family</span>
            </label>

            {roleFamilyMode === "custom" && (
              <label className="field-control">
                <span>Custom family name</span>
                <input
                  value={customRoleFamily}
                  onInput={(event) => setCustomRoleFamily(event.target.value)}
                  placeholder="Data Platform"
                  required
                />
                <small className="field-hint">
                  {selectedRoleFamilyId
                    ? `Will be saved as ${selectedRoleFamilyId}`
                    : "Use letters or numbers so RoleRadar can create a stable family ID."}
                </small>
              </label>
            )}

            <label className="field-control">
              <span>Location</span>
              <input
                value={location}
                onInput={(event) => setLocation(event.target.value)}
                placeholder="Singapore"
              />
            </label>

            <div className="field-row">
              <label className="field-control">
                <span>Results per page</span>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={resultsPerPage}
                  onInput={(event) => setResultsPerPage(event.target.value)}
                />
              </label>

              <label className="field-control">
                <span>Pages</span>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={maxPages}
                  onInput={(event) => setMaxPages(event.target.value)}
                />
              </label>
            </div>
          </div>

          <div className="form-actions">
            <button
              className="action-button primary"
              disabled={isLoading || !canSubmit}
            >
              {isLoading ? <Loader2 size={16} /> : <Play size={16} />}
              <span>{isLoading ? "Loading" : "Load Listings"}</span>
            </button>
            {result && (
              <a className="action-button" href="#/jobs">
                <BriefcaseBusiness size={16} />
                <span>View Evidence</span>
              </a>
            )}
          </div>
        </form>

        <section className="panel">
          <PanelHeader
            title="Run Result"
            subtitle="Per-source ingestion summary for this request."
          />

          {error && <div className="notice error compact">{error}</div>}

          {!result && !error && (
            <EmptyState text="No source load has been run yet." />
          )}

          {result && (
            <div className="result-list">
              <div className="result-summary">
                <strong>{formatNumber(result.data.source_listings_upserted)}</strong>
                <span>source listings upserted</span>
                <span>
                  Assigned to{" "}
                  {result.data.role_family_label ||
                    resultRoleFamily?.label ||
                    roleFamilyLabel(result.data.role_family, roleFamilies) ||
                    selectedRoleFamilyLabel ||
                    "Unknown"}
                </span>
              </div>
              {result.data.results.map((item) => (
                <div className="result-row" key={item.source}>
                  <span>
                    <strong>{sourceLabel(item.source)}</strong>
                    <small>{item.error_message || `${item.jobs_seen} jobs seen`}</small>
                  </span>
                  <span className={`badge ${item.status === "completed" ? "" : "muted"}`}>
                    {item.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </section>
    </>
  );
}

function OverviewView({
  payload,
  route,
  setSelected,
  selectedRoleFamily,
  setSelectedRoleFamily,
}) {
  const data = payload.data;
  const isExplorer = route.startsWith("#/explorer");
  const selectedRole = data.selected_role_family;
  const [companySearch, setCompanySearch] = React.useState("");
  const [sourceFilter, setSourceFilter] = React.useState("");
  const [roleFilter, setRoleFilter] = React.useState("");
  const [salaryFilter, setSalaryFilter] = React.useState("");
  const [selectedCompanyName, setSelectedCompanyName] = React.useState("");

  if (!isExplorer) {
    return (
      <CompanyOverview
        payload={payload}
        companySearch={companySearch}
        setCompanySearch={setCompanySearch}
        sourceFilter={sourceFilter}
        setSourceFilter={setSourceFilter}
        roleFilter={roleFilter}
        setRoleFilter={setRoleFilter}
        salaryFilter={salaryFilter}
        setSalaryFilter={setSalaryFilter}
        selectedCompanyName={selectedCompanyName}
        setSelectedCompanyName={setSelectedCompanyName}
        setSelected={setSelected}
      />
    );
  }

  return (
    <>
      <PageHeader
        eyebrow={isExplorer ? "Unified Explorer" : "Market Overview"}
        title={
          isExplorer
            ? "Browse current demand by skill, source, and salary signal"
            : "Singapore job-market intelligence"
        }
        meta={
          selectedRole
            ? `${selectedRole.label} · ${formatNumber(data.kpis.source_listings)} source listings`
            : `${payload.meta.total_records_in_db} source listings`
        }
        actions={<CsvActions />}
      />

      <section className="kpi-strip">
        <Metric
          label="Canonical jobs"
          value={data.kpis.canonical_jobs}
          icon={BriefcaseBusiness}
          onClick={() => setSelected(metricDetail("Canonical jobs", data.kpis))}
        />
        <Metric
          label="Companies"
          value={data.kpis.companies}
          icon={Building2}
          onClick={() => setSelected(metricDetail("Companies", data.kpis))}
        />
        <Metric
          label="Skills"
          value={data.kpis.skills}
          icon={Database}
          onClick={() => setSelected(metricDetail("Skills", data.kpis))}
        />
        <Metric
          label="Salary coverage"
          value={data.kpis.salary_disclosure_rate}
          icon={Gauge}
          formatter={formatValue}
          tone="amber"
          onClick={() => setSelected(data.salary.coverage)}
        />
      </section>

      <RoleFamiliesPanel
        rows={data.role_families || []}
        selectedRoleFamily={selectedRoleFamily}
        setSelectedRoleFamily={setSelectedRoleFamily}
        setSelected={setSelected}
      />

      <section className="analysis-grid">
        <SkillChart rows={data.top_skills} roleFamily={selectedRole} />
        <HiringCompaniesPanel
          rows={data.top_hiring_companies || []}
          roleFamily={selectedRole}
          setSelected={setSelected}
        />
        <DemandSignalsPanel
          rows={data.company_demand_signals || []}
          setSelected={setSelected}
        />
      </section>

      <section className="analysis-grid secondary">
        <ListPanel
          title="Source Quality"
          subtitle="Full-text availability by source"
          rows={data.skill_extraction_coverage}
          label="source"
          value="full_text_rate"
          formatter={(value) => `${Math.round(value * 100)}%`}
        />
        <ListPanel
          title="Salary Coverage"
          subtitle="Employer-disclosed salary share"
          rows={data.salary.by_source}
          label="group"
          value="disclosure_rate"
          formatter={(value) => `${Math.round(value * 100)}%`}
        />
        <ListPanel
          title="Recent Ingestion Runs"
          subtitle="Latest local pipeline activity"
          rows={data.recent_ingestion_runs}
          label="source"
          value="status"
        />
      </section>

      <footer className="meta-line">
        Generated {new Date(payload.meta.generated_at).toLocaleString()}.{" "}
        {data.trend_caveat}
      </footer>
    </>
  );
}

function RoleFamiliesPanel({
  rows,
  selectedRoleFamily,
  setSelectedRoleFamily,
  setSelected,
}) {
  const selectedRow = rows.find((row) => row.id === selectedRoleFamily);

  return (
    <section className="panel role-family-panel">
      <PanelHeader
        title="Canonical Role Families"
        subtitle="Normalized demand across messy source titles"
      />

      <div className="role-family-toolbar">
        <label className="field-control">
          <span>Analyze family</span>
          <select
            value={selectedRoleFamily}
            onChange={(event) => setSelectedRoleFamily(event.target.value)}
          >
            <option value="">All canonical role families</option>
            {rows.map((row) => (
              <option value={row.id} key={row.id}>
                {row.label}
              </option>
            ))}
          </select>
        </label>
        {selectedRow && (
          <button
            className="action-button"
            onClick={() => setSelectedRoleFamily("")}
          >
            <span>Clear filter</span>
          </button>
        )}
      </div>

      {!rows.length ? (
        <EmptyState text="No role-family signals yet. Load listings to classify role demand." />
      ) : (
        <div className="role-family-list">
          {rows.map((row) => (
            <button
              className={`role-family-row ${
                row.id === selectedRoleFamily ? "active" : ""
              }`}
              key={row.id}
              onClick={() => setSelectedRoleFamily(row.id)}
              onDoubleClick={() => setSelected(row)}
            >
              <span className="role-family-main">
                <strong>{row.label}</strong>
                <small>{roleFamilySubtitle(row)}</small>
              </span>
              <span className="role-family-metric">
                <strong>{formatNumber(row.job_count)}</strong>
                <small>jobs</small>
              </span>
              <span className="role-family-metric">
                <strong>{formatNumber(row.company_count)}</strong>
                <small>companies</small>
              </span>
              <span className="role-family-metric salary">
                <strong>{formatAnnualSalary(row.average_annualized_salary)}</strong>
                <small>avg salary</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function CompanyOverview({
  payload,
  companySearch,
  setCompanySearch,
  sourceFilter,
  setSourceFilter,
  roleFilter,
  setRoleFilter,
  salaryFilter,
  setSalaryFilter,
  selectedCompanyName,
  setSelectedCompanyName,
  setSelected,
}) {
  const data = payload.data;
  const companies = data.top_hiring_companies || [];
  const sourceRows = data.skill_extraction_coverage || [];
  const latestRun = data.recent_ingestion_runs?.[0];
  const errorRunCount = (data.recent_ingestion_runs || []).filter(
    (run) => run.status !== "completed" || run.error_message,
  ).length;
  const salaryCoveragePercent = Math.round(
    (data.kpis.salary_disclosure_rate || 0) * 100,
  );
  const latestCompanySeenAt = Math.max(
    0,
    ...companies.map((company) => new Date(company.latest_seen_at || 0).getTime()),
  );
  const latestSeenCompanyCount = latestCompanySeenAt
    ? companies.filter(
        (company) =>
          new Date(company.latest_seen_at || 0).getTime() === latestCompanySeenAt,
      ).length
    : 0;
  const companiesWithSalaryEstimate = Math.round(
    (data.kpis.companies || 0) * (data.kpis.salary_disclosure_rate || 0),
  );
  const sourceOptionsForCompanies = uniqueSorted(
    companies.flatMap((company) =>
      (company.top_sources || []).map((item) => item.source),
    ),
  );
  const roleOptionsForCompanies = uniqueSorted(
    companies.flatMap((company) =>
      (company.top_role_families || []).map((item) => item.role_family),
    ),
  );
  const filteredCompanies = companies.filter((company) => {
    const name = company.company_name || "UNKNOWN";
    const roles = company.top_role_families || [];
    const sources = company.top_sources || [];
    const matchesSearch = name
      .toLowerCase()
      .includes(companySearch.trim().toLowerCase());
    const matchesSource =
      !sourceFilter || sources.some((item) => item.source === sourceFilter);
    const matchesRole =
      !roleFilter || roles.some((item) => item.role_family === roleFilter);
    const matchesSalary =
      !salaryFilter ||
      (salaryFilter === "with_salary" && salaryCoveragePercent > 0) ||
      (salaryFilter === "without_salary" && salaryCoveragePercent === 0);
    return matchesSearch && matchesSource && matchesRole && matchesSalary;
  });
  const selectedCompany =
    filteredCompanies.find(
      (company) => company.company_name === selectedCompanyName,
    ) ||
    filteredCompanies[0] ||
    null;

  React.useEffect(() => {
    if (
      selectedCompany &&
      selectedCompany.company_name !== selectedCompanyName
    ) {
      setSelectedCompanyName(selectedCompany.company_name);
    }
  }, [selectedCompany, selectedCompanyName, setSelectedCompanyName]);

  return (
    <section className="company-overview">
      <div className="company-overview-topbar">
        <div className="company-overview-brand">RoleRadar</div>
        <CsvActions />
      </div>

      <div className="company-overview-heading">
        <div className="eyebrow">Companies</div>
        <h1>Hiring companies</h1>
        <p>Track employer demand across Singapore job sources.</p>
      </div>

      <section className="company-kpi-grid">
        <CompanyMetric
          value={data.kpis.companies}
          label="Companies hiring"
          onClick={() => setSelected(metricDetail("Companies", data.kpis))}
        />
        <CompanyMetric
          value={latestSeenCompanyCount}
          label="New this run"
          onClick={() => setSelected(latestRun || { key: "No ingestion run" })}
        />
        <CompanyMetric
          value={companiesWithSalaryEstimate}
          label="With salary data"
          onClick={() => setSelected(data.salary.coverage)}
        />
        <CompanyMetric
          value={(data.kpis.pending_duplicates || 0) + errorRunCount}
          label="With errors / warnings"
          onClick={() =>
            setSelected({
              key: "Errors / warnings",
              pending_duplicates: data.kpis.pending_duplicates || 0,
              recent_run_issues: errorRunCount,
            })
          }
        />
      </section>

      <DemandSignalsPanel
        rows={data.company_demand_signals || []}
        setSelected={setSelected}
      />

      <section className="company-filters" aria-label="Company filters">
        <label className="company-search">
          <Search size={16} />
          <input
            value={companySearch}
            onInput={(event) => setCompanySearch(event.target.value)}
            placeholder="Search companies..."
          />
        </label>
        <CompanySelect
          label="Source"
          value={sourceFilter}
          onChange={setSourceFilter}
          options={sourceOptionsForCompanies}
          allLabel="All"
          formatter={sourceLabel}
        />
        <CompanySelect
          label="Role"
          value={roleFilter}
          onChange={setRoleFilter}
          options={roleOptionsForCompanies}
          allLabel="All"
        />
        <CompanySelect
          label="Salary"
          value={salaryFilter}
          onChange={setSalaryFilter}
          options={["with_salary", "without_salary"]}
          allLabel="Any"
          formatter={(value) =>
            value === "with_salary" ? "With salary" : "No salary"
          }
        />
      </section>

      <CompanyTable
        rows={filteredCompanies}
        selectedCompany={selectedCompany}
        setSelectedCompanyName={setSelectedCompanyName}
        setSelected={setSelected}
      />

      <div className="selected-company-label">
        Selected company:{" "}
        <strong>{selectedCompany?.company_name || "No company selected"}</strong>
      </div>

      <CompanySnapshot
        company={selectedCompany}
        sourceRows={sourceRows}
        salaryCoveragePercent={salaryCoveragePercent}
      />

      <footer className="meta-line">
        Generated {new Date(payload.meta.generated_at).toLocaleString()}.{" "}
        {data.trend_caveat}
      </footer>
    </section>
  );
}

function CompanyMetric({ value, suffix = "", label, onClick }) {
  return (
    <button className="company-metric" onClick={onClick}>
      <strong>
        {formatNumber(value)}
        {suffix}
      </strong>
      <span>{label}</span>
    </button>
  );
}

function CompanySelect({
  label,
  value,
  onChange,
  options,
  allLabel,
  formatter = (item) => item,
}) {
  return (
    <label className="company-select">
      <span>{label}:</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{allLabel}</option>
        {options.map((option) => (
          <option value={option} key={option}>
            {formatter(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function CompanyTable({
  rows,
  selectedCompany,
  setSelectedCompanyName,
  setSelected,
}) {
  if (!rows.length) {
    return <EmptyState text="No companies match the active filters." />;
  }

  return (
    <div className="company-table-shell">
      <table className="company-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Active jobs</th>
            <th>Top roles</th>
            <th>Sources</th>
            <th>Health</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((company) => {
            const selected =
              selectedCompany?.company_name === company.company_name;
            return (
              <tr
                className={selected ? "selected" : ""}
                key={company.company_name || "UNKNOWN"}
                onClick={() => {
                  setSelectedCompanyName(company.company_name);
                  setSelected({ key: company.company_name, ...company });
                }}
              >
                <td>{company.company_name || "UNKNOWN"}</td>
                <td>{formatNumber(company.job_count)}</td>
                <td>{companyTopRoles(company)}</td>
                <td>{companySources(company)}</td>
                <td>{companyHealth(company)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CompanySnapshot({ company, sourceRows, salaryCoveragePercent }) {
  if (!company) {
    return (
      <section className="company-snapshot-grid">
        <EmptyState text="Select a company to see employer details." />
      </section>
    );
  }

  const roles = company.top_role_families || [];
  const sources = company.top_sources || [];
  const sourceNames = sources.map((item) => item.source);
  const sourceQuality = sourceRows.filter((row) => sourceNames.includes(row.source));

  return (
    <section className="company-snapshot-grid">
      <div className="company-snapshot-card">
        <h2>Employer snapshot</h2>
        <dl>
          <div>
            <dt>Active jobs:</dt>
            <dd>{formatNumber(company.job_count)}</dd>
          </div>
          <div>
            <dt>Sources:</dt>
            <dd>{companySources(company)}</dd>
          </div>
          <div>
            <dt>Salary coverage:</dt>
            <dd>{salaryCoveragePercent}%</dd>
          </div>
          <div>
            <dt>Last seen:</dt>
            <dd>{relativeTime(company.latest_seen_at)}</dd>
          </div>
          {!!sourceQuality.length && (
            <div>
              <dt>Source quality:</dt>
              <dd>
                {sourceQuality
                  .map(
                    (row) =>
                      `${sourceLabel(row.source)} ${Math.round(
                        row.full_text_rate * 100,
                      )}%`,
                  )
                  .join(", ")}
              </dd>
            </div>
          )}
        </dl>
      </div>
      <div className="company-snapshot-card">
        <h2>Open roles</h2>
        {roles.length ? (
          <ul className="company-role-list">
            {roles.map((role) => (
              <li key={role.role_family}>
                <span>{role.role_family}</span>
                <small>{formatNumber(role.job_count)} jobs</small>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState text="No role-family data for this employer." />
        )}
      </div>
    </section>
  );
}

function HiringCompaniesPanel({ rows, roleFamily, setSelected }) {
  return (
    <section className="panel">
      <PanelHeader
        title={roleFamily ? `Top Hiring Companies: ${roleFamily.label}` : "Top Hiring Companies"}
        subtitle={
          roleFamily
            ? "Ranked within the selected canonical role family"
            : "Ranked by active canonical jobs"
        }
      />

      {!rows.length ? (
        <EmptyState text="No company hiring signals yet." />
      ) : (
        <div className="hiring-company-list">
          {rows.map((row) => (
            <button
              className="hiring-company-row"
              key={row.company_name}
              onClick={() => setSelected({ key: row.company_name, ...row })}
            >
              <span className="hiring-company-main">
                <strong>{row.company_name || "UNKNOWN"}</strong>
                <small>{hiringCompanySubtitle(row)}</small>
              </span>
              <span className="hiring-company-metric">
                <strong>{formatNumber(row.job_count)}</strong>
                <small>jobs</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function DemandSignalsPanel({ rows, setSelected }) {
  return (
    <section className="panel">
      <PanelHeader
        title="Company Demand"
        subtitle="Mass-hiring signal from active and newly observed listings"
      />

      {!rows.length ? (
        <EmptyState text="No company demand signals yet." />
      ) : (
        <div className="hiring-company-list">
          {rows.slice(0, 8).map((row) => (
            <button
              className="hiring-company-row"
              key={row.company_name}
              onClick={() => setSelected({ key: row.company_name, ...row })}
            >
              <span className="hiring-company-main">
                <strong>{row.company_name || "UNKNOWN"}</strong>
                <small>
                  {formatNumber(row.new_listing_count_7d)} new 7d ·{" "}
                  {formatNumber(row.role_family_count)} role families
                </small>
              </span>
              <span className="hiring-company-metric">
                <strong>{formatNumber(row.active_listing_count)}</strong>
                <small>active listings</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function SkillChart({ rows, roleFamily }) {
  const canvasRef = React.useRef(null);

  React.useEffect(() => {
    if (!canvasRef.current || !rows.length) return undefined;
    const chart = new Chart(canvasRef.current, {
      type: "bar",
      data: {
        labels: rows.map((row) => row.skill_name),
        datasets: [
          {
            label: "Active jobs",
            data: rows.map((row) => row.job_count),
            borderRadius: 6,
            backgroundColor: "#0d9488",
            hoverBackgroundColor: "#2563eb",
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: "rgba(100, 116, 139, 0.16)" } },
          y: { grid: { display: false } },
        },
      },
    });
    return () => chart.destroy();
  }, [rows]);

  return (
    <section className="panel chart-panel">
      <PanelHeader
        title={roleFamily ? `Top Skills: ${roleFamily.label}` : "Top Skills"}
        subtitle={
          roleFamily
            ? "Current active jobs in the selected canonical role family"
            : "Current active canonical job count"
        }
      />
      {rows.length ? (
        <div className="chart-box">
          <canvas ref={canvasRef} />
        </div>
      ) : (
        <EmptyState text="No job data detected. Run roleradar ingest or review Admin imports." />
      )}
    </section>
  );
}

function TrendsView({
  payload,
  roleFamilies,
  trendRoleFamily,
  setTrendRoleFamily,
  trendSkill,
  setTrendSkill,
  trendWeeks,
  setTrendWeeks,
  setSelected,
}) {
  const data = payload.data;
  const skillRows = data.skill_demand || [];
  const salaryRows = data.salary_trend || [];
  const velocityRows = data.posting_velocity || [];
  const companyRows = data.company_hiring_velocity || [];
  const latestSkillRow = skillRows[skillRows.length - 1];
  const latestVelocityRow = velocityRows[velocityRows.length - 1];
  const selectedRoleLabel = data.selected_role_family || "All role families";

  return (
    <>
      <PageHeader
        eyebrow="Trend Engine"
        title="Track momentum, not just current demand"
        meta={`${data.weeks} weeks · ${selectedRoleLabel}`}
        actions={<CsvActions />}
      />

      <section className="panel trend-controls-panel">
        <PanelHeader
          title="Trend filters"
          subtitle="Choose the observation window, role family, and skill to track."
        />
        <div className="trend-controls">
          <label className="field-control">
            <span>Weeks</span>
            <select
              value={trendWeeks}
              onChange={(event) => setTrendWeeks(Number(event.target.value))}
            >
              {[4, 8, 12, 26, 52].map((weeks) => (
                <option value={weeks} key={weeks}>
                  {weeks} weeks
                </option>
              ))}
            </select>
          </label>
          <label className="field-control">
            <span>Role family</span>
            <select
              value={trendRoleFamily}
              onChange={(event) => setTrendRoleFamily(event.target.value)}
            >
              <option value="">All role families</option>
              {roleFamilies.map((row) => (
                <option value={row.id} key={row.id}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field-control">
            <span>Skill</span>
            <input
              list="trend-skill-options"
              value={trendSkill}
              onInput={(event) => setTrendSkill(event.target.value)}
              placeholder={data.selected_skill || "Python"}
            />
            <datalist id="trend-skill-options">
              {(data.top_skills || []).map((row) => (
                <option value={row.skill_name} key={row.skill_name} />
              ))}
            </datalist>
          </label>
          <button
            className="action-button"
            onClick={() => {
              setTrendRoleFamily("");
              setTrendSkill("");
              setTrendWeeks(12);
            }}
          >
            Clear filters
          </button>
        </div>
      </section>

      <section className="trend-kpi-grid">
        <TrendKpiCard
          label="Selected skill"
          value={data.selected_skill || "No skill"}
          detail={
            latestSkillRow
              ? `${formatSignedNumber(latestSkillRow.delta)} WoW`
              : "No observations"
          }
          onClick={() => setSelected({ key: "Skill trend", ...latestSkillRow })}
        />
        <TrendKpiCard
          label="New postings this week"
          value={latestVelocityRow?.new_posting_count || 0}
          detail={`${latestVelocityRow?.closed_posting_count || 0} closed`}
          onClick={() => setSelected({ key: "Posting velocity", ...latestVelocityRow })}
        />
        <TrendKpiCard
          label="Median time to close"
          value={formatDays(data.time_to_close?.median_days)}
          detail={`${formatNumber(data.time_to_close?.posting_count || 0)} closed jobs`}
          onClick={() => setSelected({ key: "Time to close", ...data.time_to_close })}
        />
        <TrendKpiCard
          label="P75 time to close"
          value={formatDays(data.time_to_close?.p75_days)}
          detail="Apply before slowest quartile closes"
          onClick={() => setSelected({ key: "Time to close", ...data.time_to_close })}
        />
      </section>

      <section className="trend-grid">
        <TrendChart
          title="Skill demand over time"
          subtitle={`Active jobs mentioning ${data.selected_skill || "selected skill"}`}
          rows={skillRows}
          datasets={[
            { label: "Active jobs", key: "count", color: "#0d9488" },
          ]}
        />
        <TrendChart
          title="Posting velocity"
          subtitle="New postings and closures per ISO week"
          rows={velocityRows}
          datasets={[
            { label: "New", key: "new_posting_count", color: "#2563eb" },
            { label: "Closed", key: "closed_posting_count", color: "#f97316" },
          ]}
        />
      </section>

      <section className="trend-grid secondary">
        <TrendChart
          title="Salary trend"
          subtitle="Average annualized midpoint for selected role family"
          rows={salaryRows}
          datasets={[
            {
              label: "Annualized midpoint",
              key: "average_annualized_midpoint",
              color: "#7c3aed",
            },
          ]}
          valueFormatter={formatAnnualSalary}
        />
        <CompanyVelocityPanel rows={companyRows} setSelected={setSelected} />
      </section>

      <footer className="meta-line">
        Generated {new Date(payload.meta.generated_at).toLocaleString()}. {data.caveat}
      </footer>
    </>
  );
}

function TrendKpiCard({ label, value, detail, onClick }) {
  return (
    <button className="trend-kpi-card" onClick={onClick}>
      <span>{label}</span>
      <strong>{typeof value === "number" ? formatNumber(value) : value}</strong>
      <small>{detail}</small>
    </button>
  );
}

function TrendChart({ title, subtitle, rows, datasets, valueFormatter = formatValue }) {
  const canvasRef = React.useRef(null);
  const hasValues = rows.some((row) =>
    datasets.some((dataset) => typeof row[dataset.key] === "number"),
  );

  React.useEffect(() => {
    if (!canvasRef.current || !hasValues) return undefined;
    const chart = new Chart(canvasRef.current, {
      type: "line",
      data: {
        labels: rows.map((row) => formatWeek(row.week_start)),
        datasets: datasets.map((dataset) => ({
          label: dataset.label,
          data: rows.map((row) => row[dataset.key]),
          borderColor: dataset.color,
          backgroundColor: dataset.color,
          borderWidth: 2,
          pointRadius: 3,
          tension: 0.28,
          spanGaps: true,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              label: (context) =>
                `${context.dataset.label}: ${valueFormatter(context.parsed.y)}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false } },
          y: { grid: { color: "rgba(100, 116, 139, 0.16)" } },
        },
      },
    });
    return () => chart.destroy();
  }, [rows, datasets, hasValues, valueFormatter]);

  return (
    <section className="panel chart-panel">
      <PanelHeader title={title} subtitle={subtitle} />
      {hasValues ? (
        <div className="chart-box">
          <canvas ref={canvasRef} />
        </div>
      ) : (
        <EmptyState text="No trend data yet. Run repeated ingestion to accumulate observations." />
      )}
    </section>
  );
}

function CompanyVelocityPanel({ rows, setSelected }) {
  const companyRows = Object.values(
    rows.reduce((acc, row) => {
      const key = row.company_name || "UNKNOWN";
      acc[key] = acc[key] || { company_name: key, total_new_postings: 0, weeks: [] };
      acc[key].total_new_postings += row.new_posting_count || 0;
      acc[key].weeks.push(row);
      return acc;
    }, {}),
  ).sort((left, right) =>
    right.total_new_postings - left.total_new_postings ||
    left.company_name.localeCompare(right.company_name),
  );

  return (
    <section className="panel">
      <PanelHeader
        title="Company hiring velocity"
        subtitle="Companies adding the most postings in the selected window"
      />
      {!companyRows.length ? (
        <EmptyState text="No company velocity data in this window." />
      ) : (
        <div className="trend-table-shell">
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>New postings</th>
                <th>Latest active week</th>
              </tr>
            </thead>
            <tbody>
              {companyRows.slice(0, 10).map((row) => {
                const latestWeek = row.weeks[row.weeks.length - 1];
                return (
                  <tr key={row.company_name} onClick={() => setSelected(row)}>
                    <td>{row.company_name}</td>
                    <td>{formatNumber(row.total_new_postings)}</td>
                    <td>{formatWeek(latestWeek?.week_start)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function JobsView({
  payload,
  setSelected,
  query,
  roleFamily,
  setRoleFamily,
  roleFamilies,
  onDelete,
}) {
  const rows = payload.data.items;

  return (
    <>
      <PageHeader
        eyebrow="Evidence Browser"
        title="Inspect the listings behind every signal"
        meta={`${payload.data.total} listings`}
        actions={<CsvActions query={query} roleFamily={roleFamily} />}
      />
      <section className="panel evidence-filter-panel">
        <div className="evidence-filters">
          <label className="field-control">
            <span>Role family</span>
            <select
              value={roleFamily}
              onChange={(event) => setRoleFamily(event.target.value)}
            >
              <option value="">All role families</option>
              {roleFamilies.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <div className="filter-summary">
            <strong>{formatNumber(payload.data.total)}</strong>
            <span>matching listings</span>
          </div>
        </div>
      </section>

      {!rows.length ? (
        <EmptyState text="No results match active filters. Try clearing search fields." />
      ) : (
        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>Role</th>
                <th>Company</th>
                <th>Source</th>
                <th>Structured sections</th>
                <th>Salary</th>
                <th>Last seen</th>
                <th style={{ width: "48px" }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.source_listing_id} onClick={() => setSelected(item)}>
                  <td>
                    <strong>{item.title}</strong>
                    <span>{item.location || "Location unavailable"}</span>
                  </td>
                  <td>{item.company_name || "UNKNOWN"}</td>
                  <td>
                    <span className="badge">{item.source}</span>
                  </td>
                  <td>
                    <SectionBadges item={item} />
                  </td>
                  <td>{formatSalary(item)}</td>
                  <td>
                    {item.last_seen_at
                      ? new Date(item.last_seen_at).toLocaleDateString()
                      : ""}
                  </td>
                  <td onClick={(event) => event.stopPropagation()}>
                    <button
                      className="icon-button delete-row-button"
                      onClick={() => onDelete(item)}
                      title="Delete Listing"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function SectionBadges({ item }) {
  const sections = [
    ["Responsibilities", item.responsibilities],
    ["Required", item.required_competencies_and_certifications],
    ["Preferred", item.preferred_competencies_and_qualifications],
  ].filter(([, value]) => Boolean(value));

  if (!sections.length) {
    return <span className="muted-text">None parsed</span>;
  }

  return (
    <div className="section-badges">
      {sections.map(([label, value]) => (
        <span className="section-chip" title={value} key={label}>
          {label}
        </span>
      ))}
    </div>
  );
}

function AdminView({
  payload,
  setPayload,
  setSelected,
  refreshCounter,
  setRefreshCounter,
  showToast,
}) {
  const rows = payload.data.items;
  const duplicateListingGroups =
    (payload.data.source_listing_duplicate_groups || 0) +
    (payload.data.field_duplicate_listing_groups || 0);
  const [dedupeResult, setDedupeResult] = React.useState(null);
  const [dedupeError, setDedupeError] = React.useState(null);
  const [isDeduping, setIsDeduping] = React.useState(false);
  const [deletedListings, setDeletedListings] = React.useState([]);

  React.useEffect(() => {
    let isCurrent = true;
    api("/api/v1/admin/deleted-listings")
      .then((res) => {
        if (isCurrent) setDeletedListings(res.data.items || []);
      })
      .catch((err) => console.error("Failed to load deleted listings:", err));
    return () => {
      isCurrent = false;
    };
  }, [refreshCounter]);

  const handleRestore = async (sourceListingId) => {
    try {
      await api(`/api/v1/jobs/${sourceListingId}/restore`, { method: "POST" });
      setRefreshCounter((prev) => prev + 1);
      showToast("Restored listing successfully.");
    } catch (err) {
      showToast(`Failed to restore: ${err.message}`);
    }
  };

  const runSourceListingDedupe = async () => {
    setDedupeError(null);
    setDedupeResult(null);
    setIsDeduping(true);
    try {
      const response = await api("/api/v1/admin/source-listings/dedupe", {
        method: "POST",
      });
      setDedupeResult(response.data);
      const refreshed = await api("/api/v1/admin/duplicates?limit=50");
      setPayload(refreshed);
    } catch (err) {
      setDedupeError(err.message);
    } finally {
      setIsDeduping(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Admin"
        title="Review ingestion and duplicate quality gates"
        meta={`${payload.data.total} pending candidates`}
      />
      <section className="panel">
        <PanelHeader
          title="Dedupe Scan"
          subtitle="Repair exact source IDs and detect cross-source duplicate candidates"
        />
        <div className="result-list">
          <div className="result-summary">
            <strong>{formatNumber(duplicateListingGroups)}</strong>
            <span>duplicate listing groups</span>
          </div>
          <div className="form-actions">
            <button
              className="action-button primary"
              onClick={runSourceListingDedupe}
              disabled={isDeduping}
            >
              {isDeduping ? <Loader2 size={16} /> : <Database size={16} />}
              <span>{isDeduping ? "Deduping" : "Run Dedupe"}</span>
            </button>
          </div>
          {dedupeError && (
            <div className="notice error compact">{dedupeError}</div>
          )}
          {dedupeResult && (
            <>
              <div className="result-row">
                <span>
                  <strong>
                    {formatNumber(dedupeResult.duplicate_candidates_created || 0)}
                  </strong>
                  <small>
                    duplicate candidates created,{" "}
                    {formatNumber(
                      dedupeResult.duplicate_candidates_refreshed || 0,
                    )}{" "}
                    refreshed
                  </small>
                </span>
                <span className="badge">
                  {formatNumber(dedupeResult.duplicate_candidate_pairs_found || 0)}{" "}
                  matches
                </span>
              </div>
              <div className="result-row">
                <span>
                  <strong>
                    {formatNumber(dedupeResult.source_listings_removed)}
                  </strong>
                  <small>
                    source listings removed,{" "}
                    {formatNumber(dedupeResult.observations_moved)} observations moved
                  </small>
                </span>
                <span className="badge">
                  {formatNumber(
                    (dedupeResult.groups_merged || 0) +
                      (dedupeResult.field_groups_merged || 0),
                  )}{" "}
                  groups
                </span>
              </div>
            </>
          )}
        </div>
      </section>
      {!rows.length ? (
        <EmptyState text="No pending duplicate candidates." />
      ) : (
        <section className="panel">
          <PanelHeader
            title="Duplicate Candidates"
            subtitle="Manual review queue for cross-source matches"
          />
          <div className="review-list">
            {rows.map((row) => (
              <button
                className="review-row"
                key={row.id}
                onClick={() => setSelected(row)}
              >
                <span>
                  <strong>{row.job.title}</strong>
                  <small>{row.candidate_job.title}</small>
                </span>
                <span className="score">{Math.round(row.score * 100)}%</span>
                <span className="badge muted">{row.status}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="panel" style={{ marginTop: "16px" }}>
        <PanelHeader
          title="Recycle Bin"
          subtitle="Temporary storage for deleted listings (automatically cleared after 2 days)."
        />
        {!deletedListings.length ? (
          <EmptyState text="Recycle bin is empty." />
        ) : (
          <div className="review-list">
            {deletedListings.map((item) => (
              <div
                className="review-row"
                key={item.source_listing_id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1fr) auto auto",
                  alignItems: "center",
                  gap: "12px",
                  padding: "12px 0",
                  borderBottom: "1px solid var(--border-main)",
                }}
              >
                <span style={{ display: "grid", gap: "3px" }}>
                  <strong>{item.title}</strong>
                  <small>{item.company_name} · <span className="badge">{item.source}</span></small>
                </span>
                <span style={{ fontSize: "12px", color: "var(--text-soft)" }}>
                  Deleted {formatAgo(item.deleted_at)}
                </span>
                <button
                  className="action-button primary compact"
                  onClick={() => handleRestore(item.source_listing_id)}
                  style={{ minHeight: "28px", padding: "0 10px", fontSize: "12px" }}
                >
                  Restore
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function CsvActions({ query = "", roleFamily = "" } = {}) {
  const exportParams = new URLSearchParams();
  if (query) exportParams.set("q", query);
  if (roleFamily) exportParams.set("role_family", roleFamily);
  const exportUrl = `/api/v1/jobs/export.csv${
    exportParams.toString() ? `?${exportParams.toString()}` : ""
  }`;

  return (
    <div className="header-actions">
      <a className="action-button" href={exportUrl} target="_blank">
        <Database size={16} />
        <span>Open CSV</span>
      </a>
      <a className="action-button primary" href={exportUrl} download>
        <Download size={16} />
        <span>Download</span>
      </a>
    </div>
  );
}

function PageHeader({ eyebrow, title, meta, actions }) {
  return (
    <header className="page-header">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
      </div>
      <div className="page-header-side">
        <span className="header-meta">{meta}</span>
        {actions}
      </div>
    </header>
  );
}

function Metric({ label, value, icon: Icon, formatter = formatNumber, tone, onClick }) {
  return (
    <button className={`metric ${tone || ""}`} onClick={onClick}>
      <span className="metric-icon">
        <Icon size={18} />
      </span>
      <span className="metric-label">{label}</span>
      <strong>{formatter(value)}</strong>
    </button>
  );
}

function PanelHeader({ title, subtitle }) {
  return (
    <div className="panel-header">
      <div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

function ListPanel({ title, subtitle, rows, label, value, formatter = formatValue }) {
  return (
    <section className="panel">
      <PanelHeader title={title} subtitle={subtitle} />
      {!rows.length ? (
        <EmptyState text="No data available." />
      ) : (
        <div className="signal-list">
          {rows.map((row, index) => (
            <div className="signal-row" key={`${title}-${index}`}>
              <span>{row[label] == null ? "UNKNOWN" : row[label]}</span>
              <strong>{formatter(row[value])}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function Inspector({ selected, setSelected }) {
  const sectionEntries = selected ? structuredSectionEntries(selected) : [];
  const sectionKeys = new Set(sectionEntries.map(([key]) => key));

  return (
    <aside className="inspector">
      {selected && (
        <>
          <div className="inspector-header">
            <div>
              <span>Inspector</span>
              <strong>{selected.title || selected.key || selected.status || "Details"}</strong>
            </div>
            <button className="icon-button" onClick={() => setSelected(null)} title="Close">
              <X size={18} />
            </button>
          </div>
          {!!sectionEntries.length && (
            <div className="inspector-sections">
              {sectionEntries.map(([key, label, value]) => (
                <div className="section-detail" key={key}>
                  <span>{label}</span>
                  <p>{value}</p>
                </div>
              ))}
            </div>
          )}
          <div className="inspector-body">
            {Object.entries(selected)
              .filter(([key]) => !sectionKeys.has(key))
              .map(([key, value]) => (
                <div className="detail-block" key={key}>
                  <span>{key.replaceAll("_", " ")}</span>
                  <strong>{formatDetail(value)}</strong>
                </div>
              ))}
          </div>
        </>
      )}
    </aside>
  );
}

function LoadingState() {
  return (
    <div className="loading-state">
      <Activity size={22} />
      <span>Loading RoleRadar data...</span>
    </div>
  );
}

function EmptyState({ text }) {
  return <div className="empty-state">{text}</div>;
}

function getRouteSection(route) {
  if (route.startsWith("#/jobs")) return "jobs";
  if (route.startsWith("#/admin")) return "admin";
  if (route.startsWith("#/load")) return "load";
  if (route.startsWith("#/trends")) return "trends";
  return "overview";
}

function getPayloadKey(
  routeSection,
  query,
  roleFamily,
  overviewRoleFamily,
  trendRoleFamily,
  trendSkill,
  trendWeeks,
) {
  if (routeSection === "jobs") return `jobs:${query}:${roleFamily}`;
  if (routeSection === "overview") return `overview:${overviewRoleFamily}`;
  if (routeSection === "trends") {
    return `trends:${trendRoleFamily}:${trendSkill}:${trendWeeks}`;
  }
  return routeSection;
}

function metricDetail(key, values) {
  return { key, ...values };
}

function formatNumber(value) {
  if (typeof value !== "number") return String(value ?? "");
  return new Intl.NumberFormat("en-SG").format(value);
}

function formatValue(value) {
  if (typeof value !== "number") return String(value ?? "");
  if (value > 0 && value < 1) return `${Math.round(value * 100)}%`;
  return formatNumber(value);
}

function formatSalary(item) {
  if (item.salary_min == null && item.salary_max == null) return "Not disclosed";
  return `${item.salary_currency || ""} ${item.salary_min || ""}-${item.salary_max || ""}`.trim();
}

function formatAnnualSalary(value) {
  if (typeof value !== "number") return "n/a";
  return `SGD ${new Intl.NumberFormat("en-SG", {
    maximumFractionDigits: 0,
  }).format(value)}`;
}

function formatWeek(value) {
  if (!value) return "—";
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-SG", {
    day: "2-digit",
    month: "short",
  });
}

function formatSignedNumber(value) {
  if (typeof value !== "number") return "n/a";
  if (value > 0) return `+${formatNumber(value)}`;
  return formatNumber(value);
}

function formatDays(value) {
  if (typeof value !== "number") return "n/a";
  return `${new Intl.NumberFormat("en-SG", {
    maximumFractionDigits: 1,
  }).format(value)} days`;
}

function roleFamilySubtitle(row) {
  const skills = (row.top_skills || [])
    .slice(0, 3)
    .map((item) => item.skill_name)
    .join(", ");
  const sources = (row.top_sources || [])
    .slice(0, 2)
    .map((item) => item.source)
    .join(", ");
  if (skills && sources) return `${skills} · ${sources}`;
  return skills || sources || (row.example_titles || []).slice(0, 2).join(", ");
}

function hiringCompanySubtitle(row) {
  const roles = (row.top_role_families || [])
    .slice(0, 2)
    .map((item) => item.role_family)
    .join(", ");
  const listingCount = formatNumber(row.source_listing_count || 0);
  if (roles) return `${roles} · ${listingCount} source listings`;
  return `${listingCount} source listings`;
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((left, right) =>
    String(left).localeCompare(String(right)),
  );
}

function companyTopRoles(company) {
  const roles = (company.top_role_families || [])
    .slice(0, 2)
    .map((item) => item.role_family)
    .join(", ");
  return roles || "—";
}

function companySources(company) {
  const sources = (company.top_sources || [])
    .slice(0, 2)
    .map((item) => sourceLabel(item.source))
    .join(", ");
  return sources || "—";
}

function companyHealth(company) {
  if (!company.job_count) return "No active jobs";
  if (!company.source_listing_count) return "Parser warning";
  return "Healthy";
}

function relativeTime(value) {
  if (!value) return "Unknown";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "Unknown";
  const diffSeconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (diffSeconds < 60) return "Just now";
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes} min ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} hr ago`;
  const diffDays = Math.round(diffHours / 24);
  return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;
}

function formatDetail(value) {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function sourceLabel(value) {
  const option = sourceOptions.find((item) => item.value === value);
  return option ? option.label : value;
}

function normalizeCustomRoleFamilyLabel(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function customRoleFamilyId(value) {
  const slug = normalizeCustomRoleFamilyLabel(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 120);
  return slug ? `${customRoleFamilyPrefix}${slug}` : "";
}

function roleFamilyLabel(roleFamilyId, roleFamilies = []) {
  const catalogRole = roleFamilies.find((item) => item.id === roleFamilyId);
  if (catalogRole) return catalogRole.label;
  if (!roleFamilyId?.startsWith(customRoleFamilyPrefix)) return roleFamilyId;
  const slug = roleFamilyId.slice(customRoleFamilyPrefix.length);
  if (!/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(slug)) return roleFamilyId;
  return slug
    .split("_")
    .map((word) => customRoleFamilyAcronyms.get(word) || capitalize(word))
    .join(" ");
}

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function structuredSectionEntries(item) {
  return [
    ["responsibilities", "Responsibilities", item.responsibilities],
    [
      "required_competencies_and_certifications",
      "Required competencies and certifications",
      item.required_competencies_and_certifications,
    ],
    [
      "preferred_competencies_and_qualifications",
      "Preferred competencies and qualifications",
      item.preferred_competencies_and_qualifications,
    ],
  ].filter(([, , value]) => Boolean(value));
}

function ToastContainer({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <div className="toast" key={toast.id}>
          <span className="toast-message">{toast.message}</span>
          {toast.actionLabel && (
            <button
              className="toast-action"
              onClick={() => {
                toast.onAction();
                onDismiss(toast.id);
              }}
            >
              {toast.actionLabel}
            </button>
          )}
          <button className="toast-close" onClick={() => onDismiss(toast.id)}>
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
