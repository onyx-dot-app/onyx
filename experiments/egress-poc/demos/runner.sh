#!/usr/bin/env bash
# Runs every NN_*.sh demo against both sandboxes and prints a summary table.
# Avoids bash 4+ features so it works under macOS's stock /bin/bash (3.2).
#
# Exit code: non-zero if any demo FAILed in any sandbox (SKIP doesn't fail).

set -uo pipefail

cd "$(dirname "$0")" || exit 1

ANY_FAIL=0
SUMMARY=""  # collected lines for the final table

echo "============================================================"
echo " egress-poc demo run"
echo "============================================================"

# Sorted list of demo scripts (NN_*.sh). Filenames are well-known and ASCII,
# so glob+sort is fine here (no need for find's -print0 dance).
# shellcheck disable=SC2012  # filenames are controlled (NN_*.sh); ls is appropriate
DEMOS=$(ls [0-9][0-9]_*.sh 2>/dev/null | sort)

for demo in $DEMOS; do
    desc=$(grep -E '^DEMO_DESC=' "./$demo" | head -1 \
           | sed -E 's/^DEMO_DESC="(.*)"$/\1/')

    for sb in sandbox-explicit sandbox-transparent; do
        bash "./$demo" "$sb"
        rc=$?
        case "$rc" in
            0) result="PASS" ;;
            2) result="SKIP" ;;
            *) result="FAIL"; ANY_FAIL=1 ;;
        esac
        # Stash "demo|sandbox|result|desc" for the summary phase.
        SUMMARY="${SUMMARY}${demo}|${sb}|${result}|${desc}"$'\n'
    done
done

echo ""
echo "============================================================"
echo " Summary"
echo "============================================================"
printf '%-44s  %-10s  %-12s\n' "Demo" "EXPLICIT" "TRANSPARENT"
printf '%-44s  %-10s  %-12s\n' "----" "--------" "-----------"

for demo in $DEMOS; do
    desc=""
    explicit_result="?"
    transparent_result="?"
    while IFS='|' read -r d sb r dsc; do
        [ -z "$d" ] && continue
        if [ "$d" = "$demo" ]; then
            desc="$dsc"
            case "$sb" in
                sandbox-explicit)    explicit_result="$r" ;;
                sandbox-transparent) transparent_result="$r" ;;
            esac
        fi
    done <<EOF
$SUMMARY
EOF
    printf '%-44s  %-10s  %-12s\n' "$desc" "$explicit_result" "$transparent_result"
done

exit $ANY_FAIL
