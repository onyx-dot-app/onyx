# Build Mode Connector Audit Report

## Connectors in Build Mode
1. GoogleDrive
2. Gmail
3. Notion
4. GitHub
5. Slack
6. Linear
7. Fireflies
8. Hubspot

## Issues Found

### Issue 1: Missing `groups` parameter in connector creation
**Location**: `/web/src/app/build/v1/configure/utils/createBuildConnector.ts:52-61`

**Problem**: The `createConnector` call passes `access_type: "private"` but doesn't include `groups: []`. While the backend defaults to empty list, it's better to be explicit.

**Status**: ✅ Will fix

### Issue 2: Step flow logic - Advanced values only connectors show as 2-step
**Location**: `/web/src/app/build/v1/configure/components/ConfigureConnectorModal.tsx:24-36`

**Problem**: The `connectorNeedsConfigStep` function checks both `values` and `advanced_values`. Connectors that only have `advanced_values` (like Slack) incorrectly show as 2-step when they should be 1-step.

**Connectors affected**:
- **Slack**: `values: []`, `advanced_values: [channels, channel_regex_enabled]` → Currently 2-step, should be 1-step

**Status**: ✅ Will fix

## Connector-by-Connector Analysis

### 1. GoogleDrive ✅
- **Config**: Has `values` (indexing_scope tab with fields) and `advanced_values` (specific_user_emails, exclude_domain_link_only)
- **Step Flow**: 2-step ✅ CORRECT
- **access_type**: ✅ Included in createConnector call
- **groups**: ❌ Missing (will add)

### 2. Gmail ✅
- **Config**: `values: []`, `advanced_values: []`
- **Step Flow**: 1-step ✅ CORRECT
- **access_type**: ✅ Included in createConnector call
- **groups**: ❌ Missing (will add)

### 3. Notion ✅
- **Config**: Has `values` (root_page_id), `advanced_values: []`
- **Step Flow**: 2-step ✅ CORRECT
- **access_type**: ✅ Included in createConnector call
- **groups**: ❌ Missing (will add)

### 4. GitHub ✅
- **Config**: Has `values` (repo_owner, github_mode, include_prs, include_issues), `advanced_values: []`
- **Step Flow**: 2-step ✅ CORRECT
- **access_type**: ✅ Included in createConnector call
- **groups**: ❌ Missing (will add)

### 5. Slack ❌
- **Config**: `values: []`, `advanced_values: [channels, channel_regex_enabled]`
- **Step Flow**: 2-step ❌ INCORRECT (should be 1-step)
- **access_type**: ✅ Included in createConnector call
- **groups**: ❌ Missing (will add)
- **Fix**: Update `connectorNeedsConfigStep` to only check `values`, not `advanced_values`

### 6. Linear ✅
- **Config**: `values: []`, `advanced_values: []`
- **Step Flow**: 1-step ✅ CORRECT
- **access_type**: ✅ Included in createConnector call
- **groups**: ❌ Missing (will add)

### 7. Fireflies ✅
- **Config**: `values: []`, `advanced_values: []`
- **Step Flow**: 1-step ✅ CORRECT
- **access_type**: ✅ Included in createConnector call
- **groups**: ❌ Missing (will add)

### 8. Hubspot ✅
- **Config**: Has `values` (object_types), `advanced_values: []`
- **Step Flow**: 2-step ✅ CORRECT
- **access_type**: ✅ Included in createConnector call
- **groups**: ❌ Missing (will add)

## Summary
- **Total connectors**: 8
- **Step flow issues**: 1 (Slack)
- **access_type issues**: 0 (all connectors include it)
- **groups issues**: 8 (all missing, but backend defaults to [])

## Fixes Required
1. Add `groups: []` to `createConnector` call in `createBuildConnector.ts`
2. Update `connectorNeedsConfigStep` to only check `values`, not `advanced_values`
