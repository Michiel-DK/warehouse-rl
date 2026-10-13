"""Static tests for the provisioned Grafana dashboard (fleet/grafana/dashboard.json) and its provisioning. No Docker, no
network, none skipped. The panel SQL is checked against fleet/sql/schema.sql (parsed here, nothing hard-coded): every
table after FROM / JOIN and every other identifier must be a table / column of the DDL, an alias the query defines, a
function call, or a SQL keyword. Each case names its red demonstration in an `# inject:` comment."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet.tests.test_fleet_clickhouse_store import parse_create  # noqa: E402
from fleet_analyser.clickhouse_store import split_statements  # noqa: E402

FLEET = ROOT / "fleet"
DASHBOARD = FLEET / "grafana" / "dashboard.json"
PROVISIONING = FLEET / "grafana" / "provisioning"
SCHEMA = FLEET / "sql" / "schema.sql"
REPORT_SQL = FLEET / "sql" / "reports"
ROWS = ["INTEGRATION", "SIMULATION", "RESULTS"]
KEYWORDS = {
    "select", "from", "where", "group", "by", "order", "limit", "having", "with", "as", "and", "or", "not", "in", "is",
    "null", "distinct", "asc", "desc", "final", "join", "left", "inner", "right", "on", "using", "union", "all", "between",
    "like", "case", "when", "then", "else", "end", "true", "false", "interval", "format", "prewhere", "sample", "array",
}


def schema():
    """{table: set of column names} from schema.sql."""
    return {t["name"]: set(t["cols"]) for t in map(parse_create, split_statements(SCHEMA.read_text()))}


def unknown_names(sql, tables):
    """Names in `sql` that are neither a known table / column, an alias the query defines, a function nor a keyword.
    Tables are the identifiers after FROM / JOIN; columns may come from any table the query names."""
    text = re.sub(r"--[^\n]*", " ", sql)
    text = re.sub(r"'(?:[^'\\]|\\.)*'", "''", text)  # string literals (also ${run} placeholders inside them)
    text = text.replace("`", "")
    bad = []
    used = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)", text, re.I)
    bad += [f"table {t}" for t in used if t not in tables]
    cols = set().union(*(tables[t] for t in used if t in tables)) if used else set()
    aliases = set(re.findall(r"\bAS\s+([A-Za-z_]\w*)", text, re.I))
    functions = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", text))
    for m in re.finditer(r"(?<![\w.])([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?", text):
        head, tail = m.group(1), m.group(2)
        if head in used and tail is None and re.match(r"\s*(FINAL|AS|,|\)|JOIN|LEFT|INNER|WHERE|ON|$)", text[m.end():], re.I):
            continue  # a table name in FROM / JOIN position
        name = tail if tail is not None else head
        if tail is not None and head not in aliases and head not in tables:
            bad.append(f"qualifier {head}")
        if name.lower() in KEYWORDS or name in functions or name in aliases or name in cols or name in tables:
            continue
        bad.append(f"column {name}")
    return sorted(set(bad))


def all_panels(panels):
    """Every panel, including the ones nested in collapsed rows."""
    for p in panels:
        yield p
        yield from all_panels(p.get("panels", []))


def datasource_uid():
    m = re.search(r"^\s*uid:\s*(\S+)\s*$", (PROVISIONING / "datasources" / "clickhouse.yaml").read_text(), re.M)
    return m.group(1)


class TestDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dash = json.loads(DASHBOARD.read_text())
        cls.panels = list(all_panels(cls.dash["panels"]))
        cls.query_panels = [p for p in cls.panels if p.get("targets")]
        cls.tables = schema()

    def test_the_three_rows_are_present_with_exactly_these_titles(self):
        # inject: rename a row (for example Integration), or drop RESULTS
        rows = [p["title"] for p in self.panels if p["type"] == "row"]
        self.assertEqual(rows, ROWS)

    def test_every_row_has_query_panels_below_it(self):
        # inject: move all panels above the first row
        under, cur = {}, None
        for p in self.dash["panels"]:
            if p["type"] == "row":
                cur = p["title"]
                under[cur] = list(p.get("panels", []))
            else:
                under[cur].append(p)
        for title in ROWS:
            self.assertTrue([p for p in under[title] if p.get("targets")], title)

    def test_every_panel_query_names_only_schema_tables_and_columns(self):
        # inject: rename a column in a panel query (for example lag_p50 for lag_p50_s) or query a table schema.sql lacks
        self.assertGreater(len(self.query_panels), 10)
        for p in self.query_panels:
            for t in p["targets"]:
                with self.subTest(panel=p["title"]):
                    self.assertEqual(unknown_names(t["rawSql"], self.tables), [])

    def test_the_variable_query_is_checked_too(self):
        # inject: point the run variable at a table that does not exist
        (var,) = self.dash["templating"]["list"]
        self.assertEqual(unknown_names(var["query"], self.tables), [])

    def test_the_name_checker_catches_what_it_should_and_lets_aliases_functions_and_params_through(self):
        # inject: make unknown_names return [] always, or stop checking tables
        t = self.tables
        ok = ("SELECT d.kind AS k, if(g.status = 'graded', JSONExtractString(g.verdict), 'open') AS verdict, count() AS n "
              "FROM decisions AS d LEFT JOIN (SELECT id, status, verdict FROM decision_grades FINAL) AS g ON d.id = g.id "
              "WHERE d.run = '${run}' GROUP BY k, verdict ORDER BY k ASC")
        self.assertEqual(unknown_names(ok, t), [])
        self.assertEqual(unknown_names("SELECT `key`, argMax(value, loaded_at) AS v FROM results GROUP BY `key`", t), [])
        self.assertEqual(unknown_names("SELECT lag_p50 FROM ingest_ledger FINAL", t), ["column lag_p50"])
        self.assertEqual(unknown_names("SELECT run FROM nope", t), ["column run", "table nope"])
        self.assertEqual(unknown_names("SELECT x.run FROM ingest_ledger AS y", t), ["qualifier x"])
        self.assertEqual(unknown_names("SELECT run -- a comment with bogus_col\nFROM ingest_ledger WHERE run = 'bogus_str'", t), [])

    def test_every_query_panel_and_target_uses_the_provisioned_datasource_uid(self):
        # inject: change one panel's datasource uid, or drop the datasource from a target
        uid = datasource_uid()
        self.assertEqual(uid, "fleet-clickhouse")
        for p in self.query_panels:
            self.assertEqual(p["datasource"]["uid"], uid, p["title"])
            for t in p["targets"]:
                self.assertEqual(t["datasource"]["uid"], uid, p["title"])
        (var,) = self.dash["templating"]["list"]
        self.assertEqual(var["datasource"]["uid"], uid)

    def test_row_panels_carry_no_query(self):
        # inject: add a target to a row panel
        for p in self.panels:
            if p["type"] == "row":
                self.assertNotIn("targets", p)

    def test_every_report_sql_file_is_a_panel_query(self):
        # inject: edit a panel's SQL away from its fleet/sql/reports file
        queries = {t["rawSql"] for p in self.query_panels for t in p["targets"]}
        files = sorted(REPORT_SQL.glob("*.sql"))
        self.assertTrue(files)
        for f in files:
            body = "\n".join(ln for ln in f.read_text().splitlines() if not ln.lstrip().startswith("--")).strip()
            self.assertIn(body.replace("{run:String}", "'${run}'"), queries, f.name)

    def test_results_panels_read_the_results_table(self):
        # inject: point the RESULTS panels at stuck_episodes
        res = [p for p in self.query_panels if "FROM results" in p["targets"][0]["rawSql"]]
        self.assertGreaterEqual(len(res), 3)


class TestProvisioning(unittest.TestCase):
    def compose_mounts(self):
        """[(host path, container path)] of the grafana service's volumes in docker-compose.yml (line parse: no yaml lib)."""
        text = (FLEET / "docker-compose.yml").read_text()
        block = re.search(r"^  grafana:\n(.*?)(?=^  \w|\Z)", text, re.M | re.S).group(1)
        vols = re.search(r"^    volumes:\n((?:      - .*\n)+)", block, re.M).group(1)
        out = []
        for ln in vols.splitlines():
            parts = ln.strip()[2:].split(":")
            out.append((parts[0], parts[1]))
        return out

    def test_fleet_yaml_provisions_the_dashboard_from_the_path_compose_mounts(self):
        # inject: change the provider path in fleet.yaml, or the container side of the compose mount
        yml = (PROVISIONING / "dashboards" / "fleet.yaml").read_text()
        path = re.search(r"^\s*path:\s*(\S+)\s*$", yml, re.M).group(1)
        self.assertIn("type: file", yml)
        provisioned = None
        for src, dst in self.compose_mounts():
            host = (FLEET / src).resolve()
            if host == DASHBOARD.resolve():
                provisioned = str(Path(dst).parent)  # a single file mounted into the dashboards directory
            elif host == DASHBOARD.parent.resolve():
                provisioned = dst
        self.assertIsNotNone(provisioned, "docker-compose.yml does not mount dashboard.json")
        self.assertEqual(path, provisioned)
        self.assertIn(("./grafana/provisioning", "/etc/grafana/provisioning"), self.compose_mounts())

    def test_the_provisioned_datasource_is_the_clickhouse_one(self):
        # inject: rename the datasource uid in clickhouse.yaml (the dashboard test then goes red too)
        self.assertEqual(datasource_uid(), "fleet-clickhouse")
        self.assertIn("grafana-clickhouse-datasource", (PROVISIONING / "datasources" / "clickhouse.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
