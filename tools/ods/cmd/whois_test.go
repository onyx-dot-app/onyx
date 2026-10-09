package cmd

import (
	"bytes"
	"slices"
	"strings"
	"testing"
)

// kubeKubectlScript fakes kubectl for whois: the context exists, one api-server
// pod is ready, and pginto prints execOutput. $5 is the verb after the
// --context/--namespace flags.
func kubeKubectlScript(execOutput string) string {
	return `case "$5" in
  get) printf 'api-server-0 False\nweb-server-1 True\napi-server-1 True\n' ;;
  exec) printf '` + execOutput + `' ;;
esac
`
}

// kubeExecSQL returns the SQL of the last pginto call, after checking it ran
// on the ready api-server pod of the prod cluster.
func kubeExecSQL(t *testing.T, calls [][]string) string {
	t.Helper()
	kubectl := kubeCallsTo(calls, "kubectl")
	last := kubectl[len(kubectl)-1]
	prefix := []string{"--context", "prod", "--namespace", "onyx", "exec", "api-server-1", "--", "pginto", "-A", "-t", "-F", "\t", "-c"}
	if len(last) != len(prefix)+1 || strings.Join(last[:len(prefix)], "|") != strings.Join(prefix, "|") {
		t.Fatalf("expected a pginto exec on the api-server pod, got %q", last)
	}
	return last[len(prefix)]
}

func TestWhois_emailSearchEscapesTheFragmentAndPrintsATable(t *testing.T) {
	t.Setenv("KUBE_CTX_STAGING", "  prod   us-east-2 onyx ")
	calls := kubeFakeTools(t, map[string]string{
		"kubectl": kubeKubectlScript(`Connecting to db...\n a@x.com\tt1\ttrue \n\nbob@x.com\tt2\tfalse\n`),
	})

	out := kubeExecute(t, NewWhoisCommand(), "-c", "staging", `o'b_r%;"\`)

	want := "\n" +
		"EMAIL      TENANT ID  ACTIVE\n" +
		"-----      ---------  ------\n" +
		"a@x.com    t1         true\n" +
		"bob@x.com  t2         false\n"
	if out != want {
		t.Fatalf("expected %q, got %q", want, out)
	}

	got := calls()
	if kubectl := kubeCallsTo(got, "kubectl"); len(kubectl) != 3 || kubectl[0][0] != "config" || kubectl[1][4] != "get" {
		t.Fatalf("expected get-contexts, get po, exec; got %q", kubectl)
	}
	// Quotes and semicolons are dropped; LIKE wildcards and backslashes are escaped.
	wantSQL := `SELECT email, tenant_id, active FROM public.user_tenant_mapping WHERE email LIKE '%ob\_r\%\\%' ORDER BY email;`
	if sql := kubeExecSQL(t, got); sql != wantSQL {
		t.Fatalf("expected %q, got %q", wantSQL, sql)
	}
}

func TestWhois_tenantLookupListsAdmins(t *testing.T) {
	t.Setenv("KUBE_CTX_DATA_PLANE", "prod us-east-2 onyx")
	calls := kubeFakeTools(t, map[string]string{
		"kubectl": kubeKubectlScript(`admin@x.com\nowner@x.com\n`),
	})

	var out bytes.Buffer
	if err := runWhois(&out, "tenant_ab-12", "data_plane"); err != nil {
		t.Fatalf("runWhois failed: %v", err)
	}

	if want := "\nEMAIL\n-----\nadmin@x.com\nowner@x.com\n"; out.String() != want {
		t.Fatalf("expected %q, got %q", want, out.String())
	}
	wantSQL := `SELECT email FROM "tenant_ab-12"."user" WHERE role = 'ADMIN' AND is_active = true AND email NOT LIKE 'api_key__%' ORDER BY email;`
	if sql := kubeExecSQL(t, calls()); sql != wantSQL {
		t.Fatalf("expected %q, got %q", wantSQL, sql)
	}
}

func TestWhois_reportsEmptyResults(t *testing.T) {
	cases := []struct {
		query string
		want  string
	}{
		{"chris", "No results found.\n"},
		{"tenant_abc", "No admin users found for this tenant.\n"},
	}
	for _, c := range cases {
		t.Run(c.query, func(t *testing.T) {
			t.Setenv("KUBE_CTX_DATA_PLANE", "prod us-east-2 onyx")
			kubeFakeTools(t, map[string]string{
				"kubectl": kubeKubectlScript(`Connecting to db...\n\n`),
			})

			var out bytes.Buffer
			if err := runWhois(&out, c.query, "data_plane"); err != nil {
				t.Fatalf("runWhois failed: %v", err)
			}

			if out.String() != c.want {
				t.Fatalf("expected %q, got %q", c.want, out.String())
			}
		})
	}
}

// The tenant ID is interpolated into a quoted schema name, so the guard must
// stop the query before it reaches the pod.
func TestWhois_rejectsAnUnsafeTenantID(t *testing.T) {
	t.Setenv("KUBE_CTX_DATA_PLANE", "prod us-east-2 onyx")
	calls := kubeFakeTools(t, map[string]string{
		"kubectl": kubeKubectlScript(`admin@x.com\n`),
	})

	var out bytes.Buffer
	err := runWhois(&out, "tenant_x y", "data_plane")

	if want := `Invalid tenant ID: "tenant_x y" (must be alphanumeric, hyphens, underscores only)`; err == nil || err.Error() != want {
		t.Fatalf("expected %q, got %v", want, err)
	}
	if out.Len() != 0 {
		t.Fatalf("expected no output, got %q", out.String())
	}
	for _, call := range kubeCallsTo(calls(), "kubectl") {
		if slices.Contains(call, "exec") {
			t.Fatalf("expected no query, got kubectl %q", call)
		}
	}
}

// The tenant ID is interpolated into a quoted schema name, so this guard is
// what keeps SQL out of it.
func TestSafeIdentifier(t *testing.T) {
	cases := []struct {
		id   string
		want bool
	}{
		{"tenant_abcd1234-ef56", true},
		{"tenant_ABC_9", true},
		{"", false},
		{`tenant_x"."user"; DROP`, false},
		{"tenant_x y", false},
		{"tenant_x\n", false},
		{"tenant_é", false},
	}
	for _, c := range cases {
		if got := safeIdentifier.MatchString(c.id); got != c.want {
			t.Fatalf("safeIdentifier.MatchString(%q): expected %v, got %v", c.id, c.want, got)
		}
	}
}
