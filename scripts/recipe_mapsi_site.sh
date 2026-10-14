#!/usr/bin/env bash
set -euo pipefail

MODE="health"
GROWTH_URL=""
CAMPAIGN_ID=""
ASSET_ID=""
ENV_FILE=""
REPORT_FILE=""
CONFIRM_REAL_PUBLICATION=false
RESTORE_INITIAL_STATE=false
CONFIRMATION_PHRASE=""

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

LAST_HTTP_STATUS=""
LAST_RESPONSE_BODY=""

usage() {
  cat <<'EOF'
Usage:
  scripts/recipe_mapsi_site.sh [mode] [options]

Modes:
  health             Default
  preview
  publish
  status
  replay
  kill-switch-test
  feature-flag-test
  unpublish-test

Options:
  --growth-url URL
  --campaign-id ID
  --asset-id ID
  --env-file PATH
  --report-file PATH
  --confirm-real-publication
  --restore-initial-state
  --confirmation-phrase VALUE
  -h, --help

Expected env file variables:
  GROWTH_ADMIN_BEARER_TOKEN
  MAPSI_SITE_PUBLIC_BASE_URL
  MAPSI_SITE_PUBLIC_LIST_PATH=/actualites
  WORKFLOW_KILL_SWITCH_DEFAULT=false
  STUDIO_CONFIRMATION_PHRASE=CONFIRM
EOF
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

bool_to_json() {
  if [ "$1" = "true" ]; then
    printf 'true'
  else
    printf 'false'
  fi
}

json_string() {
  jq -Rn --arg value "$1" '$value'
}

check_env_file_permissions() {
  local perm
  perm="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE" 2>/dev/null || true)"
  [ -n "$perm" ] || fail "Unable to read permissions for $ENV_FILE"
  case "$perm" in
    600|400|0400|0600) ;;
    *) fail "Refusing env file with permissions $perm. Use chmod 600 $ENV_FILE" ;;
  esac
}

load_env_file() {
  [ -n "$ENV_FILE" ] || fail "--env-file is required"
  [ -f "$ENV_FILE" ] || fail "Env file not found: $ENV_FILE"
  check_env_file_permissions
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
}

api_request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local idem_key="${4:-}"
  local response_file="$TMPDIR/response.json"
  local headers=(
    -H "Authorization: Bearer ${GROWTH_ADMIN_BEARER_TOKEN}"
    -H "Accept: application/json"
    -H "Content-Type: application/json"
    -H "X-Correlation-ID: recipe-mapsi-site-$(date +%s)"
  )
  if [ -n "$idem_key" ]; then
    headers+=(-H "Idempotency-Key: $idem_key")
  fi

  local output
  if [ -n "$body" ]; then
    output="$(curl -sS -X "$method" "${headers[@]}" --data "$body" -w $'\n%{http_code}' "${GROWTH_URL%/}${path}")"
  else
    output="$(curl -sS -X "$method" "${headers[@]}" -w $'\n%{http_code}' "${GROWTH_URL%/}${path}")"
  fi

  LAST_HTTP_STATUS="$(printf '%s\n' "$output" | tail -n 1)"
  LAST_RESPONSE_BODY="$(printf '%s\n' "$output" | sed '$d')"
  printf '%s' "$LAST_RESPONSE_BODY" > "$response_file"
}

public_fetch() {
  local url="$1"
  local output
  output="$(curl -sS -L -w $'\n%{http_code}' "$url")"
  PUBLIC_HTTP_STATUS="$(printf '%s\n' "$output" | tail -n 1)"
  PUBLIC_BODY="$(printf '%s\n' "$output" | sed '$d')"
}

expect_http() {
  local expected="$1"
  [ "$LAST_HTTP_STATUS" = "$expected" ] || fail "Unexpected HTTP status for last request: got $LAST_HTTP_STATUS expected $expected. Body: $LAST_RESPONSE_BODY"
}

expect_http_any() {
  local actual="$LAST_HTTP_STATUS"
  shift
  local expected
  for expected in "$@"; do
    if [ "$actual" = "$expected" ]; then
      return 0
    fi
  done
  fail "Unexpected HTTP status for last request: got $actual expected one of: $*"
}

require_asset() {
  [ -n "$ASSET_ID" ] || fail "--asset-id is required for mode $MODE"
}

require_real_confirmation() {
  [ "$CONFIRM_REAL_PUBLICATION" = "true" ] || fail "Real publication is locked. Re-run with --confirm-real-publication"
}

require_jq_expr() {
  local expr="$1"
  local file="$2"
  local message="$3"
  jq -e "$expr" "$file" >/dev/null 2>&1 || fail "$message"
}

fetch_health() {
  api_request GET "/api/admin/v1/health"
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/health.json"
}

fetch_channel() {
  api_request GET "/api/admin/v1/channels/mapsi_site"
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/channel.json"
}

fetch_asset() {
  require_asset
  api_request GET "/api/admin/v1/assets/${ASSET_ID}"
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/asset.json"
}

fetch_preview() {
  require_asset
  api_request GET "/api/admin/v1/assets/${ASSET_ID}/preview"
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/preview.json"
}

fetch_publication() {
  require_asset
  api_request GET "/api/admin/v1/assets/${ASSET_ID}/publication"
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/publication.json"
}

fetch_status() {
  require_asset
  api_request GET "/api/admin/v1/assets/${ASSET_ID}/publication-status"
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/status.json"
}

fetch_readiness() {
  require_asset
  api_request GET "/api/admin/v1/assets/${ASSET_ID}/publication-readiness"
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/readiness.json"
}

infer_global_kill_switch_state() {
  local default_state="${WORKFLOW_KILL_SWITCH_DEFAULT:-false}"
  api_request GET "/api/admin/v1/audit-events?page=1&page_size=50"
  if [ "$LAST_HTTP_STATUS" != "200" ]; then
    jq -n --arg active "$default_state" --arg source "env_default" '{active: ($active == "true"), source: $source}' > "$TMPDIR/global_kill.json"
    return
  fi
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/audit.json"
  local latest
  latest="$(jq -r '.data | map(select(.event_type == "configuration.global_kill_switch_activated" or .event_type == "configuration.global_kill_switch_deactivated")) | sort_by(.timestamp) | last // empty' "$TMPDIR/audit.json")"
  if [ -z "$latest" ]; then
    jq -n --arg active "$default_state" --arg source "env_default" '{active: ($active == "true"), source: $source}' > "$TMPDIR/global_kill.json"
    return
  fi
  jq -n --argjson event "$latest" '{active: ($event.event_type == "configuration.global_kill_switch_activated"), source: "audit"}' > "$TMPDIR/global_kill.json"
}

capture_initial_state() {
  fetch_channel
  infer_global_kill_switch_state
  jq -n \
    --argjson channel "$(jq '.data' "$TMPDIR/channel.json")" \
    --argjson global "$(cat "$TMPDIR/global_kill.json")" \
    '{
      global_kill_switch: $global.active,
      global_kill_switch_source: $global.source,
      channel_kill_switch: $channel.emergency_kill_switch,
      feature_flag: $channel.feature_enabled
    }' > "$TMPDIR/initial_state.json"
}

capture_current_state() {
  fetch_channel
  jq -n \
    --argjson channel "$(jq '.data' "$TMPDIR/channel.json")" \
    --argjson global "$(cat "$TMPDIR/global_kill.json")" \
    '{
      global_kill_switch: $global.active,
      global_kill_switch_source: $global.source,
      channel_kill_switch: $channel.emergency_kill_switch,
      feature_flag: $channel.feature_enabled
    }' > "$TMPDIR/final_state.json"
}

ensure_public_target_healthy() {
  local base_url="${MAPSI_SITE_PUBLIC_BASE_URL:-}"
  [ -n "$base_url" ] || fail "MAPSI_SITE_PUBLIC_BASE_URL is required in env file"
  PUBLIC_LIST_URL="${base_url%/}${MAPSI_SITE_PUBLIC_LIST_PATH:-/actualites}"
  public_fetch "$PUBLIC_LIST_URL"
  [ "$PUBLIC_HTTP_STATUS" = "200" ] || fail "Public MAPSI Site list is not healthy: $PUBLIC_LIST_URL returned $PUBLIC_HTTP_STATUS"
  printf '%s' "$PUBLIC_BODY" > "$TMPDIR/public_list.html"
}

ensure_asset_publish_prerequisites() {
  fetch_asset
  fetch_readiness
  require_jq_expr '.data.asset_type == "mapsi_news_article"' "$TMPDIR/asset.json" "Asset type must be mapsi_news_article"
  require_jq_expr '.data.channel == "mapsi_site"' "$TMPDIR/asset.json" "Asset channel must be mapsi_site"
  require_jq_expr '.data.approval.status == "approved"' "$TMPDIR/asset.json" "Asset must be approved"
  require_jq_expr '.data.content_hash != "" and .data.content_hash == .data.approved_content_hash' "$TMPDIR/asset.json" "Content hash must match approved_content_hash"
  require_jq_expr '.data.status == "APPROVED"' "$TMPDIR/asset.json" "Asset status must be APPROVED"
  require_jq_expr '.data.status == "ready"' "$TMPDIR/readiness.json" "Publication readiness must be ready"
  ensure_public_target_healthy
}

ensure_preview_not_public() {
  local title
  title="$(jq -r '.data.title' "$TMPDIR/asset.json")"
  if printf '%s' "$PUBLIC_BODY" | grep -F "$title" >/dev/null 2>&1; then
    fail "Preview safety check failed: title already appears in public list: $title"
  fi
}

assert_article_unchanged() {
  local before_file="$1"
  local after_file="$2"
  local before_external after_external before_url after_url
  before_external="$(jq -r '.data.external_publication_id // ""' "$before_file")"
  after_external="$(jq -r '.data.external_publication_id // ""' "$after_file")"
  before_url="$(jq -r '.data.external_publication_url // ""' "$before_file")"
  after_url="$(jq -r '.data.external_publication_url // ""' "$after_file")"
  [ "$before_external" = "$after_external" ] || fail "Existing article changed during safety test: external_publication_id mismatch"
  [ "$before_url" = "$after_url" ] || fail "Existing article changed during safety test: public_url mismatch"
}

create_preview_operation() {
  api_request POST "/api/admin/v1/assets/${ASSET_ID}/create-preview" '{}'
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/preview_op.json"
  require_jq_expr '.data.status == "preview_ready"' "$TMPDIR/preview_op.json" "Preview operation did not return preview_ready"
  require_jq_expr '.data.preview_url != ""' "$TMPDIR/preview_op.json" "Preview URL is missing"
}

publish_operation() {
  local idem_key="$1"
  local body
  body="$(jq -n --arg idem "$idem_key" '{idempotency_key: $idem}')"
  api_request POST "/api/admin/v1/assets/${ASSET_ID}/publish" "$body" "$idem_key"
  expect_http 200
  printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/publish_${idem_key}.json"
}

status_operation() {
  fetch_status
  require_jq_expr '.data.channel == "mapsi_site"' "$TMPDIR/status.json" "Publication status channel mismatch"
}

activate_channel_kill_switch() {
  api_request POST "/api/admin/v1/channels/mapsi_site/activate-kill-switch" '{}'
  expect_http 200
}

deactivate_channel_kill_switch() {
  local confirmation="${CONFIRMATION_PHRASE}"
  api_request POST "/api/admin/v1/channels/mapsi_site/deactivate-kill-switch" "$(jq -n --arg confirmation "$confirmation" '{confirmation: $confirmation}')" ""
  expect_http 200
}

disable_feature_flag() {
  api_request POST "/api/admin/v1/channels/mapsi_site/disable" '{}'
  expect_http 200
}

enable_feature_flag() {
  local confirmation="${CONFIRMATION_PHRASE}"
  api_request POST "/api/admin/v1/channels/mapsi_site/enable" "$(jq -n --arg confirmation "$confirmation" '{confirmation: $confirmation}')" ""
  expect_http 200
}

activate_global_kill_switch() {
  api_request POST "/api/admin/v1/global-kill-switch/activate" '{}'
  expect_http 200
  jq -n '{active: true, source: "script"}' > "$TMPDIR/global_kill.json"
}

deactivate_global_kill_switch() {
  local confirmation="${CONFIRMATION_PHRASE}"
  api_request POST "/api/admin/v1/global-kill-switch/deactivate" "$(jq -n --arg confirmation "$confirmation" '{confirmation: $confirmation}')" ""
  expect_http 200
  jq -n '{active: false, source: "script"}' > "$TMPDIR/global_kill.json"
}

restore_initial_state() {
  [ "$RESTORE_INITIAL_STATE" = "true" ] || return 0
  local initial_global initial_channel_kill initial_feature current_channel_kill current_feature
  initial_global="$(jq -r '.global_kill_switch' "$TMPDIR/initial_state.json")"
  initial_channel_kill="$(jq -r '.channel_kill_switch' "$TMPDIR/initial_state.json")"
  initial_feature="$(jq -r '.feature_flag' "$TMPDIR/initial_state.json")"
  fetch_channel
  current_channel_kill="$(jq -r '.data.emergency_kill_switch' "$TMPDIR/channel.json")"
  current_feature="$(jq -r '.data.feature_enabled' "$TMPDIR/channel.json")"

  if [ "$current_channel_kill" = "true" ] && [ "$initial_channel_kill" = "false" ]; then
    echo "Restoring channel kill switch to false"
    deactivate_channel_kill_switch
  elif [ "$current_channel_kill" = "false" ] && [ "$initial_channel_kill" = "true" ]; then
    echo "Restoring channel kill switch to true"
    activate_channel_kill_switch
  fi

  if [ "$current_feature" = "false" ] && [ "$initial_feature" = "true" ]; then
    echo "Restoring feature flag to true"
    enable_feature_flag
  elif [ "$current_feature" = "true" ] && [ "$initial_feature" = "false" ]; then
    echo "Restoring feature flag to false"
    disable_feature_flag
  fi

  local current_global
  current_global="$(jq -r '.active' "$TMPDIR/global_kill.json")"
  if [ "$current_global" = "true" ] && [ "$initial_global" = "false" ]; then
    echo "Restoring global kill switch to false"
    deactivate_global_kill_switch
  elif [ "$current_global" = "false" ] && [ "$initial_global" = "true" ]; then
    echo "Restoring global kill switch to true"
    activate_global_kill_switch
  fi
}

print_restore_instructions() {
  [ "$RESTORE_INITIAL_STATE" = "true" ] && return 0
  cat <<EOF
Initial state captured in report.
No automatic restoration was requested.
To restore explicitly, rerun with:
  --restore-initial-state
EOF
}

write_report() {
  local success_json="$1"
  local preview_json publish_json replay_json status_json extra_json
  preview_json="$(cat "$TMPDIR/preview_op.json" 2>/dev/null || printf 'null')"
  publish_json="$(cat "$TMPDIR/publish.json" 2>/dev/null || printf 'null')"
  replay_json="$(cat "$TMPDIR/replay.json" 2>/dev/null || printf 'null')"
  status_json="$(cat "$TMPDIR/status.json" 2>/dev/null || printf 'null')"
  extra_json="$(cat "$TMPDIR/extra.json" 2>/dev/null || printf 'null')"

  jq -n \
    --arg mode "$MODE" \
    --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg growth_url "$GROWTH_URL" \
    --arg campaign_id "$CAMPAIGN_ID" \
    --arg asset_id "$ASSET_ID" \
    --arg public_list_url "${PUBLIC_LIST_URL:-}" \
    --argjson success "$success_json" \
    --argjson initial_state "$(cat "$TMPDIR/initial_state.json")" \
    --argjson final_state "$(cat "$TMPDIR/final_state.json")" \
    --argjson health "$(cat "$TMPDIR/health.json" 2>/dev/null || printf 'null')" \
    --argjson channel "$(cat "$TMPDIR/channel.json" 2>/dev/null || printf 'null')" \
    --argjson asset "$(cat "$TMPDIR/asset.json" 2>/dev/null || printf 'null')" \
    --argjson readiness "$(cat "$TMPDIR/readiness.json" 2>/dev/null || printf 'null')" \
    --argjson publication "$(cat "$TMPDIR/publication.json" 2>/dev/null || printf 'null')" \
    --argjson preview "$preview_json" \
    --argjson publish "$publish_json" \
    --argjson replay "$replay_json" \
    --argjson status "$status_json" \
    --argjson extra "$extra_json" \
    '{
      mode: $mode,
      timestamp: $timestamp,
      success: $success,
      inputs: {
        growth_url: $growth_url,
        campaign_id: $campaign_id,
        asset_id: $asset_id,
        public_list_url: $public_list_url
      },
      initial_state: $initial_state,
      final_state: $final_state,
      health: $health,
      channel: $channel,
      asset: $asset,
      readiness: $readiness,
      publication: $publication,
      preview_operation: $preview,
      publish_operation: $publish,
      replay_operation: $replay,
      status_operation: $status,
      extra: $extra
    }' > "$REPORT_FILE"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      health|preview|publish|status|replay|kill-switch-test|feature-flag-test|unpublish-test)
        MODE="$1"
        ;;
      --growth-url)
        GROWTH_URL="$2"
        shift
        ;;
      --campaign-id)
        CAMPAIGN_ID="$2"
        shift
        ;;
      --asset-id)
        ASSET_ID="$2"
        shift
        ;;
      --env-file)
        ENV_FILE="$2"
        shift
        ;;
      --report-file)
        REPORT_FILE="$2"
        shift
        ;;
      --confirm-real-publication)
        CONFIRM_REAL_PUBLICATION=true
        ;;
      --restore-initial-state)
        RESTORE_INITIAL_STATE=true
        ;;
      --confirmation-phrase)
        CONFIRMATION_PHRASE="$2"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
    shift
  done
}

main() {
  need_cmd curl
  need_cmd jq
  parse_args "$@"
  load_env_file
  GROWTH_URL="${GROWTH_URL:-${GROWTH_ADMIN_URL:-}}"
  [ -n "$GROWTH_URL" ] || fail "--growth-url is required"
  [ -n "${GROWTH_ADMIN_BEARER_TOKEN:-}" ] || fail "GROWTH_ADMIN_BEARER_TOKEN is required in env file"
  CONFIRMATION_PHRASE="${CONFIRMATION_PHRASE:-${STUDIO_CONFIRMATION_PHRASE:-CONFIRM}}"
  REPORT_FILE="${REPORT_FILE:-$PWD/mapsi-site-recipe-report-$(date +%Y%m%d-%H%M%S).json}"

  capture_initial_state
  fetch_health
  fetch_channel

  case "$MODE" in
    health)
      if [ -n "$ASSET_ID" ]; then
        fetch_asset
        fetch_publication
      fi
      ensure_public_target_healthy
      jq -n '{check: "health_ok"}' > "$TMPDIR/extra.json"
      ;;
    preview)
      require_asset
      ensure_asset_publish_prerequisites
      ensure_preview_not_public
      create_preview_operation
      ensure_public_target_healthy
      ensure_preview_not_public
      fetch_preview
      fetch_publication
      jq -n --arg preview_url "$(jq -r '.data.preview_url' "$TMPDIR/preview_op.json")" '{preview_created: true, preview_url: $preview_url, public_list_unchanged: true}' > "$TMPDIR/extra.json"
      ;;
    publish)
      require_asset
      require_real_confirmation
      ensure_asset_publish_prerequisites
      create_preview_operation
      local_idem="mapsi-site-publish-${ASSET_ID}-$(date +%s)"
      publish_operation "$local_idem"
      cp "$TMPDIR/publish_${local_idem}.json" "$TMPDIR/publish.json"
      fetch_status
      jq -n \
        --arg idem "$local_idem" \
        --arg external_id "$(jq -r '.data.external_id' "$TMPDIR/publish.json")" \
        --arg public_url "$(jq -r '.data.public_url' "$TMPDIR/publish.json")" \
        '{idempotency_key: $idem, external_publication_id: $external_id, public_url: $public_url}' > "$TMPDIR/extra.json"
      ;;
    status)
      require_asset
      fetch_asset
      fetch_publication
      status_operation
      jq -n '{status_checked: true}' > "$TMPDIR/extra.json"
      ;;
    replay)
      require_asset
      require_real_confirmation
      ensure_asset_publish_prerequisites
      create_preview_operation
      local_idem="mapsi-site-replay-${ASSET_ID}-$(date +%s)"
      publish_operation "$local_idem"
      cp "$TMPDIR/publish_${local_idem}.json" "$TMPDIR/publish.json"
      publish_operation "$local_idem"
      cp "$TMPDIR/publish_${local_idem}.json" "$TMPDIR/replay.json"
      local first_external second_external first_public second_public
      first_external="$(jq -r '.data.external_id' "$TMPDIR/publish.json")"
      second_external="$(jq -r '.data.external_id' "$TMPDIR/replay.json")"
      first_public="$(jq -r '.data.public_url' "$TMPDIR/publish.json")"
      second_public="$(jq -r '.data.public_url' "$TMPDIR/replay.json")"
      [ "$first_external" = "$second_external" ] || fail "Replay external_publication_id mismatch"
      [ "$first_public" = "$second_public" ] || fail "Replay public_url mismatch"
      jq -n \
        --arg idem "$local_idem" \
        --arg external_id "$first_external" \
        --arg public_url "$first_public" \
        '{idempotency_key: $idem, same_external_publication_id: true, same_public_url: true, idempotent_replay: true, external_publication_id: $external_id, public_url: $public_url}' > "$TMPDIR/extra.json"
      ;;
    kill-switch-test)
      require_asset
      ensure_asset_publish_prerequisites
      fetch_publication
      cp "$TMPDIR/publication.json" "$TMPDIR/publication_before_safety.json"
      local initial_channel_kill
      initial_channel_kill="$(jq -r '.channel_kill_switch' "$TMPDIR/initial_state.json")"
      if [ "$initial_channel_kill" != "true" ]; then
        activate_channel_kill_switch
      fi
      local_idem="mapsi-site-kill-${ASSET_ID}-$(date +%s)"
      api_request POST "/api/admin/v1/assets/${ASSET_ID}/publish" "$(jq -n --arg idem "$local_idem" '{idempotency_key: $idem}')" "$local_idem"
      expect_http 409
      printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/status.json"
      fetch_publication
      cp "$TMPDIR/publication.json" "$TMPDIR/publication_after_safety.json"
      assert_article_unchanged "$TMPDIR/publication_before_safety.json" "$TMPDIR/publication_after_safety.json"
      jq -n '{kill_switch_refusal_verified: true, article_unchanged_verified: true}' > "$TMPDIR/extra.json"
      restore_initial_state
      print_restore_instructions
      ;;
    feature-flag-test)
      require_asset
      ensure_asset_publish_prerequisites
      fetch_publication
      cp "$TMPDIR/publication.json" "$TMPDIR/publication_before_safety.json"
      local initial_feature
      initial_feature="$(jq -r '.feature_flag' "$TMPDIR/initial_state.json")"
      if [ "$initial_feature" != "false" ]; then
        disable_feature_flag
      fi
      local_idem="mapsi-site-flag-${ASSET_ID}-$(date +%s)"
      api_request POST "/api/admin/v1/assets/${ASSET_ID}/publish" "$(jq -n --arg idem "$local_idem" '{idempotency_key: $idem}')" "$local_idem"
      expect_http 409
      printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/status.json"
      fetch_publication
      cp "$TMPDIR/publication.json" "$TMPDIR/publication_after_safety.json"
      assert_article_unchanged "$TMPDIR/publication_before_safety.json" "$TMPDIR/publication_after_safety.json"
      jq -n '{feature_flag_refusal_verified: true, article_unchanged_verified: true}' > "$TMPDIR/extra.json"
      restore_initial_state
      print_restore_instructions
      ;;
    unpublish-test)
      require_asset
      require_real_confirmation
      fetch_publication
      require_jq_expr '.data.publication_status == "PUBLISHED"' "$TMPDIR/publication.json" "Asset must already be published before unpublish-test"
      api_request POST "/api/admin/v1/assets/${ASSET_ID}/unpublish" '{}'
      expect_http 200
      printf '%s' "$LAST_RESPONSE_BODY" > "$TMPDIR/status.json"
      jq -n '{unpublish_test_executed: true, automatic_restore_supported: false}' > "$TMPDIR/extra.json"
      ;;
    *)
      fail "Unsupported mode: $MODE"
      ;;
  esac

  capture_current_state
  write_report true
  echo "Recipe completed: $MODE"
  echo "JSON report: $REPORT_FILE"
}

main "$@"
