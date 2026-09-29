#!/bin/bash
# Copyright IBM Corp. 2026

set -e

# Parse command line arguments
PHASE=""
STEP=""
MOCK_OUTPUT_DIR=""
RESUME=false
DRYRUN=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --phase)
            PHASE="$2"
            shift 2
            ;;
        --step)
            STEP="$2"
            shift 2
            ;;
        --mock-output)
            MOCK_OUTPUT_DIR="$2"
            shift 2
            ;;
        --resume)
            RESUME=true
            shift
            ;;
        --dryrun)
            DRYRUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--phase <preprocess|generate|postprocess>] [--step <0|1|2|3>] [--mock-output <dir>]"
            echo ""
            echo "Phase Options:"
            echo "  --phase preprocess   Run only Phase 1 (Sentinel extraction)"
            echo "  --phase generate     Run only Phase 2 (Policy generation)"
            echo "  --phase postprocess  Run only Phase 3 (Deployment)"
            echo ""
            echo "Step Options (only valid with --phase generate or when running all phases):"
            echo "  --step 0             Policy Extraction"
            echo "  --step 1             Requirement Generation"
            echo "  --step 2             Policy Generation"
            echo "  --step 3             Summary Generation"
            echo ""
            echo "Mock Options:"
            echo "  --mock-output <dir>  Skip Phase 2 and use pre-generated output from <dir>"
            echo "                       Example: --mock-output archive_20260525_112836/output"
            echo ""
            echo "If no options specified, runs all phases and all steps."
            echo ""
            echo "Examples:"
            echo "  $0                           # Run all phases, all steps"
            echo "  $0 --phase preprocess        # Extract Sentinel files only"
            echo "  $0 --phase generate          # Generate policies (all steps)"
            echo "  $0 --phase generate --step 2 # Generate policies (step 2 only)"
            echo "  $0 --step 1                  # Run all phases, but only step 1 in Phase 2"
            echo "  $0 --phase postprocess       # Deploy to external repo only"
            echo "  $0 --mock-output archive_20260525_112836/output  # Test with mock data"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "External Repo Integration Pipeline"
echo "=========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Preserve environment variables that should not be overridden by .env
PRESERVED_DATA_DIR="${DATA_DIR}"
PRESERVED_INPUT_DIR="${INPUT_DIR}"
PRESERVED_OUTPUT_DIR="${OUTPUT_DIR}"
PRESERVED_INPUT_FILE="${INPUT_FILE}"

# Load environment variables from .env file
# Priority: 1. Current directory, 2. Project root
if [ -f ".env" ]; then
    echo "Loading environment variables from $(pwd)/.env..."
    set -a
    source ".env"
    set +a
    echo "✓ Environment variables loaded"
elif [ -f "${PROJECT_ROOT}/.env" ]; then
    echo "Loading environment variables from ${PROJECT_ROOT}/.env..."
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
    echo "✓ Environment variables loaded"
else
    echo "Error: .env file not found"
    echo "Please create a .env file in current directory or ${PROJECT_ROOT}/"
    echo "with EXTERNAL_REPO_DIR variable."
    exit 1
fi

# Restore preserved variables if they were already set
[ -n "$PRESERVED_DATA_DIR" ] && DATA_DIR="$PRESERVED_DATA_DIR"
[ -n "$PRESERVED_INPUT_DIR" ] && INPUT_DIR="$PRESERVED_INPUT_DIR"
[ -n "$PRESERVED_OUTPUT_DIR" ] && OUTPUT_DIR="$PRESERVED_OUTPUT_DIR"
[ -n "$PRESERVED_INPUT_FILE" ] && INPUT_FILE="$PRESERVED_INPUT_FILE"

# Check required variables
if [ -z "$EXTERNAL_REPO_DIR" ]; then
    echo "Error: EXTERNAL_REPO_DIR not set in .env file"
    echo "Please add: EXTERNAL_REPO_DIR=/path/to/external/repo"
    exit 1
fi

# Check if external repo directory exists
if [ ! -d "$EXTERNAL_REPO_DIR" ]; then
    echo "Error: External repository directory not found: $EXTERNAL_REPO_DIR"
    exit 1
fi

echo "✓ External repository found: $EXTERNAL_REPO_DIR"
echo ""

# Set default values if not set
DATA_DIR="${DATA_DIR:-./data}"

# Dry-run: show summary and exit before making any changes
if [ "$DRYRUN" = true ]; then
    echo "=========================================="
    echo "  Dry-run Summary"
    echo "=========================================="
    echo "  Input Policy Directory (external mode)  : ${EXTERNAL_REPO_DIR:-}"
    echo "  Output   : ${DATA_DIR}/output-{timestamp}  (created at runtime)"
    if [ -z "$PHASE" ] || [ "$PHASE" = "generate" ]; then
        echo "  Model    : ${AUTH_PROVIDER:-litellm} / ${MODEL_NAME:-}"
        echo "  Image    : ${IMAGE_NAME:-terraform-pac-agent-skills}:${IMAGE_TAG:-latest}"
    fi
    echo "=========================================="
    echo ""
    if [ -n "$PHASE" ]; then
        if [ "$PHASE" = "generate" ] && [ "$RESUME" = true ]; then
            echo "  Phase: generate only (resuming from latest checkpoint)"
        else
            echo "  Phase: ${PHASE} only"
        fi
    else
        echo "=========================================="
        echo "Running Full Pipeline (external mode)"
        echo "=========================================="
        echo "  Phase 1: Preprocess"
        if [ "$RESUME" = true ]; then
            echo "  Phase 2: Generate  (resuming from latest checkpoint)"
        else
            echo "  Phase 2: Generate"
        fi
        echo "  Phase 3: Postprocess"
    fi
    echo ""
    echo "ℹ️  Dry-run mode: Pipeline not executed"
    exit 0
fi

# Ensure DATA_DIR exists before resolving to an absolute path
mkdir -p "$DATA_DIR"

# Resolve DATA_DIR to absolute path from CWD
if [[ "$DATA_DIR" = /* ]]; then
    DATA_DIR_ABS="$DATA_DIR"
else
    DATA_DIR_ABS="$(cd "$DATA_DIR" && pwd)"
fi

# Determine which phases to run
RUN_PREPROCESS=false
RUN_GENERATE=false
RUN_POSTPROCESS=false

if [ -z "$PHASE" ]; then
    # No phase specified, run all
    RUN_PREPROCESS=true
    RUN_GENERATE=true
    RUN_POSTPROCESS=true
else
    case "$PHASE" in
        preprocess)
            RUN_PREPROCESS=true
            ;;
        generate)
            RUN_GENERATE=true
            ;;
        postprocess)
            RUN_POSTPROCESS=true
            ;;
        *)
            echo "Error: Invalid phase '$PHASE'"
            echo "Valid phases: preprocess, generate, postprocess"
            exit 1
            ;;
    esac
fi

# Validate --step option
if [ -n "$STEP" ] && [ "$RUN_PREPROCESS" = true ] && [ "$RUN_GENERATE" = false ]; then
    echo "Error: --step option is only valid with --phase generate or when running all phases"
    exit 1
fi

if [ -n "$STEP" ] && [ "$RUN_POSTPROCESS" = true ] && [ "$RUN_GENERATE" = false ]; then
    echo "Error: --step option is only valid with --phase generate or when running all phases"
    exit 1
fi

# Phase 1: Preprocessing
if [ "$RUN_PREPROCESS" = true ]; then
    echo "=========================================="
    echo "Phase 1: Extract Sentinel files"
    echo "=========================================="
    echo ""

    # Create timestamped directories
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    INPUT_DIR_NAME="input-${TIMESTAMP}"
    OUTPUT_DIR_NAME="output-${TIMESTAMP}"
    
    TEMP_INPUT_DIR="${DATA_DIR_ABS}/${INPUT_DIR_NAME}"
    TEMP_OUTPUT_DIR="${DATA_DIR_ABS}/${OUTPUT_DIR_NAME}"
    SENTINELS_DIR="${TEMP_INPUT_DIR}/sentinels"
    
    mkdir -p "$SENTINELS_DIR"
    mkdir -p "$TEMP_OUTPUT_DIR"

    echo "✓ Created directories:"
    echo "  Input:  $TEMP_INPUT_DIR"
    echo "  Output: $TEMP_OUTPUT_DIR"
    echo ""

    # Copy .sentinel files from external repo
    SENTINEL_COUNT=0
    SKIPPED_COUNT=0
    MOCK_COUNT=0

    while IFS= read -r -d '' sentinel_file; do
        sentinel_dir=$(dirname "$sentinel_file")
        sentinel_basename=$(basename "$sentinel_file" .sentinel)
        
        # Skip mock files in test/ directories
        if [[ "$sentinel_file" == */test/* ]]; then
            echo "⊘ Skipped: $sentinel_file (mock file in test/ directory)"
            MOCK_COUNT=$((MOCK_COUNT + 1))
            continue
        fi
        
        # Skip if policy already exists
        tfpolicy_dir="$sentinel_dir/tfpolicy/$sentinel_basename"
        policy_file="$tfpolicy_dir/$sentinel_basename.policy.hcl"
        
        if [ -f "$policy_file" ]; then
            echo "⊘ Skipped: $sentinel_file (policy already exists)"
            SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
        else
            # Copy to sentinels directory, preserving relative path
            relative_path="${sentinel_file#$EXTERNAL_REPO_DIR/}"
            target_file="$SENTINELS_DIR/$relative_path"
            target_dir=$(dirname "$target_file")
            
            mkdir -p "$target_dir"
            cp "$sentinel_file" "$target_file"
            SENTINEL_COUNT=$((SENTINEL_COUNT + 1))
            echo "✓ Copied: $relative_path"
            
            # Check for mock files in test directory (only if feature flag is enabled)
            if [ "${ENABLE_SENTINEL_MOCK_USE:-true}" = "true" ]; then
                mock_dir="$sentinel_dir/test/$sentinel_basename"
                if [ -d "$mock_dir" ]; then
                    # Copy mock directory
                    relative_mock_path="${mock_dir#$EXTERNAL_REPO_DIR/}"
                    target_mock_dir="$SENTINELS_DIR/$relative_mock_path"
                    
                    mkdir -p "$target_mock_dir"
                    cp -r "$mock_dir"/* "$target_mock_dir/" 2>/dev/null || true
                    
                    if [ "$(ls -A "$target_mock_dir" 2>/dev/null)" ]; then
                        echo "  ✓ Copied mock files: $relative_mock_path"
                    fi
                fi
            fi
        fi
    done < <(find "$EXTERNAL_REPO_DIR" -type f -name "*.sentinel" -print0)

    if [ $SENTINEL_COUNT -eq 0 ]; then
        echo ""
        echo "No new Sentinel files to process."
        echo "  Total files found: $((SENTINEL_COUNT + SKIPPED_COUNT + MOCK_COUNT))"
        echo "  Mock files (in test/): $MOCK_COUNT"
        echo "  Already have policy.hcl: $SKIPPED_COUNT"
        echo "  New files to process: $SENTINEL_COUNT"
        rm -rf "$TEMP_INPUT_DIR" "$TEMP_OUTPUT_DIR"
        exit 0
    fi

    echo ""
    echo "✓ Copied $SENTINEL_COUNT Sentinel files"
    if [ $SKIPPED_COUNT -gt 0 ]; then
        echo "  Skipped $SKIPPED_COUNT files (already have policy.hcl)"
    fi
    if [ $MOCK_COUNT -gt 0 ]; then
        echo "  Skipped $MOCK_COUNT mock files (in test/ directories)"
    fi
    echo ""

    # Copy and process sentinel.hcl if defined
    if [ -n "$SENTINEL_HCL_PATH" ] && [ -f "$SENTINEL_HCL_PATH" ]; then
        echo "Processing sentinel.hcl file..."
        cp "$SENTINEL_HCL_PATH" "$SENTINELS_DIR/sentinel.hcl"
        sed -i.bak 's|source = "[^"]*\/\([^/"]*\.sentinel\)"|source = "\1"|g' "$SENTINELS_DIR/sentinel.hcl"
        rm -f "$SENTINELS_DIR/sentinel.hcl.bak"
        echo "✓ Copied and processed sentinel.hcl"
    fi

    # Generate policy_goal.txt in INPUT_DIR
    POLICY_GOAL_FILE="${TEMP_INPUT_DIR}/policy_goal.txt"
    echo "Generating policy_goal.txt..."
    echo "Generate TF Policy for" > "$POLICY_GOAL_FILE"

    # Add all sentinel files with path relative to DATA_DIR
    # Docker mounts DATA_DIR as /workspace/data, so paths should be relative to that
    # Exclude files in test/ directories (mock files)
    while IFS= read -r -d '' sentinel_file; do
        # Skip if this is a mock file in test/ directory
        if [[ "$sentinel_file" == */test/* ]]; then
            continue
        fi
        
        relative_path="${sentinel_file#$SENTINELS_DIR/}"
        sentinel_line="./data/${INPUT_DIR_NAME}/sentinels/$relative_path"
        
        # Check if mock directory exists for this sentinel (only if feature flag is enabled)
        if [ "${ENABLE_SENTINEL_MOCK_USE:-true}" = "true" ]; then
            sentinel_basename=$(basename "$sentinel_file" .sentinel)
            sentinel_dir=$(dirname "$sentinel_file")
            mock_dir="$sentinel_dir/test/$sentinel_basename"
            
            if [ -d "$mock_dir" ] && [ "$(ls -A "$mock_dir" 2>/dev/null)" ]; then
                # Mock directory exists and is not empty
                relative_mock_path="${mock_dir#$SENTINELS_DIR/}"
                echo "- ${sentinel_line}, Mock Files: ./data/${INPUT_DIR_NAME}/sentinels/$relative_mock_path" >> "$POLICY_GOAL_FILE"
            else
                echo "- ${sentinel_line}" >> "$POLICY_GOAL_FILE"
            fi
        else
            # Feature flag disabled, don't include mock files
            echo "- ${sentinel_line}" >> "$POLICY_GOAL_FILE"
        fi
    done < <(find "$SENTINELS_DIR" -type f -name "*.sentinel" -print0 | sort -z)

    # Add sentinel.hcl reference if exists
    if [ -f "$SENTINELS_DIR/sentinel.hcl" ]; then
        echo "" >> "$POLICY_GOAL_FILE"
        echo "Enforcement level configuration file:" >> "$POLICY_GOAL_FILE"
        echo "./data/${INPUT_DIR_NAME}/sentinels/sentinel.hcl" >> "$POLICY_GOAL_FILE"
    fi

    echo "✓ Generated $POLICY_GOAL_FILE"
    echo ""
else
    # Load latest directories from previous run
    INPUT_DIR_NAME=$(ls -1dt "${DATA_DIR_ABS}"/input-* 2>/dev/null | head -n1 | xargs basename)
    OUTPUT_DIR_NAME=$(ls -1dt "${DATA_DIR_ABS}"/output-* 2>/dev/null | head -n1 | xargs basename)
    
    if [ -z "$INPUT_DIR_NAME" ] || [ -z "$OUTPUT_DIR_NAME" ]; then
        echo "Error: No previous preprocessing run found."
        echo "Please run with --phase preprocess first, or run without --phase to run all phases."
        exit 1
    fi
    
    TEMP_INPUT_DIR="${DATA_DIR_ABS}/${INPUT_DIR_NAME}"
    TEMP_OUTPUT_DIR="${DATA_DIR_ABS}/${OUTPUT_DIR_NAME}"
    POLICY_GOAL_FILE="${TEMP_INPUT_DIR}/policy_goal.txt"
    
    echo "Using directories from previous run:"
    echo "  Input:  $INPUT_DIR_NAME"
    echo "  Output: $OUTPUT_DIR_NAME"
    echo ""
fi

# Phase 2: Generate
if [ "$RUN_GENERATE" = true ]; then
    # Check if using mock output
    if [ -n "$MOCK_OUTPUT_DIR" ]; then
        echo "=========================================="
        echo "Phase 2: SKIPPED (Using Mock Output)"
        echo "=========================================="
        echo ""
        
        # Validate mock output directory
        if [ ! -d "$MOCK_OUTPUT_DIR" ]; then
            echo "Error: Mock output directory not found: $MOCK_OUTPUT_DIR"
            exit 1
        fi
        
        if [ ! -f "$MOCK_OUTPUT_DIR/summary.md" ]; then
            echo "Error: summary.md not found in mock output directory: $MOCK_OUTPUT_DIR"
            exit 1
        fi
        
        echo "Using mock output from: $MOCK_OUTPUT_DIR"
        echo ""
        
        # Copy mock output to TEMP_OUTPUT_DIR
        echo "Copying mock output data..."
        rm -rf "$TEMP_OUTPUT_DIR"
        cp -r "$MOCK_OUTPUT_DIR" "$TEMP_OUTPUT_DIR"
        echo "✓ Mock output copied to: $TEMP_OUTPUT_DIR"
        echo ""
        
    else
        echo "=========================================="
        echo "Phase 2: Run Pipeline"
        echo "=========================================="
        echo ""

        # Set environment variables for run.sh and run_pipeline.py
        export DATA_DIR="$DATA_DIR_ABS"
        export INPUT_DIR="$INPUT_DIR_NAME"
        export OUTPUT_DIR="$OUTPUT_DIR_NAME"
        export INPUT_FILE="policy_goal.txt"

        echo "Running policy generation pipeline..."
        echo "  Data Dir: $DATA_DIR_ABS"
        echo "  Input:    $INPUT_DIR_NAME"
        echo "  Output:   $OUTPUT_DIR_NAME"
        echo "  Policy:   policy_goal.txt"
        
        if [ -n "$STEP" ]; then
            echo "  Step:     $STEP"
        fi
        
        # Show Stage 4 status if enabled
        if [ "${ENABLE_STAGE4:-false}" = "true" ]; then
            echo "  Stage 4: Enabled (Validation Fixtures Generation)"
        else
            echo "  Stage 4: Disabled (set ENABLE_STAGE4=true to enable)"
        fi
        echo ""

        # Run the pipeline
        if [ -n "$STEP" ]; then
            python3 "${SCRIPT_DIR}/run_pipeline.py" --step "$STEP"
        elif [ "$RESUME" = true ]; then
            "${SCRIPT_DIR}/run.sh" --no-confirm --resume local
        else
            "${SCRIPT_DIR}/run.sh" --no-confirm local
        fi

        echo ""
    fi
fi

# Extract the target policy filenames declared inside a .policytest.hcl file.
# Prints one target per line. Handles both single-line and multi-line targets blocks.
extract_policytest_targets() {
    awk '
        /policytest[[:space:]]*\{/ { in_block = 1 }
        in_block {
            line = $0
            while (match(line, /"[^"]*"/)) {
                t = substr(line, RSTART + 1, RLENGTH - 2)
                if (t != "") print t
                line = substr(line, RSTART + RLENGTH)
            }
            if ($0 ~ /\}/) in_block = 0
        }
    ' "$1"
}

# Rewrite every quoted "<something>.policy.hcl" reference in a deployed test file so it
# points at the renamed policy file. Safe because the caller has already verified that the
# file targets only this policy directory's own policy.
rewrite_policytest_targets() {
    local file="$1"
    local new_policy_basename="$2"
    sed -i.bak -E "s|\"[A-Za-z0-9_.-]+\.policy\.hcl\"|\"${new_policy_basename}.policy.hcl\"|g" "$file"
    rm -f "$file.bak"
}

# Phase 3: Postprocessing
if [ "$RUN_POSTPROCESS" = true ]; then
    echo "=========================================="
    echo "Phase 3: Deploy to External Repository"
    echo "=========================================="
    echo ""

    # Check if summary.md exists
    summary_file="${TEMP_OUTPUT_DIR}/summary.md"
    if [ ! -f "$summary_file" ]; then
        echo "Error: summary.md not found in $TEMP_OUTPUT_DIR"
        echo "Pipeline may have failed. Please check the logs."
        exit 1
    fi

    # Arrays to track results
    declare -a DEPLOYED_POLICIES
    declare -a FAILED_POLICIES

    # Parse summary.md to get policy status
    while IFS='|' read -r _ policy_name status _ _ _ _; do
        # Skip header and separator lines
        [[ "$policy_name" =~ ^[[:space:]]*Generated[[:space:]]+TF[[:space:]]+Policy[[:space:]]+Name[[:space:]]*$ ]] && continue
        [[ "$policy_name" =~ ^[[:space:]]*-+[[:space:]]*$ ]] && continue
        [[ -z "$policy_name" ]] && continue
        
        # Trim whitespace
        policy_name=$(echo "$policy_name" | xargs)
        status=$(echo "$status" | xargs)
        
        # Normalize policy name
        normalized_policy_name=$(echo "$policy_name" | tr '[:upper:]' '[:lower:]' | tr ' _' '-')
        
        # Check status
        if [[ "$status" == *"Success"* ]] || [[ "$status" == "✅ Success" ]]; then
            policy_found=false
            for policy_dir in "${TEMP_OUTPUT_DIR}"/*/; do
                [ ! -d "$policy_dir" ] && continue
                [ "$(basename "$policy_dir")" = "goals" ] && continue
                
                policy_dir_name=$(basename "$policy_dir")
                normalized_dir_name=$(echo "$policy_dir_name" | tr '[:upper:]' '[:lower:]' | tr ' _' '-')
                
                [ "$normalized_dir_name" != "$normalized_policy_name" ] && continue
                
                # Resolve sentinel path
                report_file="$policy_dir/report.md"
                sentinel_path=""
                sentinel_basename_from_dir=$(echo "$normalized_dir_name" | tr '-' '_')
                
                # First, try to identify the input sentinel directly from input/sentinels
                if [ -d "${TEMP_INPUT_DIR}/sentinels" ]; then
                    matched_sentinel=$(find "${TEMP_INPUT_DIR}/sentinels" -type f \( -name "${normalized_dir_name}.sentinel" -o -name "${sentinel_basename_from_dir}.sentinel" \) | head -n 1)
                    if [ -n "$matched_sentinel" ]; then
                        sentinel_path="${matched_sentinel#${TEMP_INPUT_DIR}/sentinels/}"
                    fi
                fi
                
                # Fallback to report.md if direct lookup failed
                if [ -z "$sentinel_path" ]; then
                    [ ! -f "$report_file" ] && continue
                    sentinel_path=$(grep -o "sentinels/[^[:space:]]*\.sentinel" "$report_file" | head -n 1 | sed 's|sentinels/||')
                    [ -z "$sentinel_path" ] && continue
                fi
                
                # Determine target directory
                sentinel_dir=$(dirname "$sentinel_path")
                sentinel_basename=$(basename "$sentinel_path" .sentinel)
                
                if [ "$sentinel_dir" = "." ]; then
                    target_dir="$EXTERNAL_REPO_DIR/tfpolicy/$sentinel_basename"
                else
                    target_dir="$EXTERNAL_REPO_DIR/$sentinel_dir/tfpolicy/$sentinel_basename"
                fi
                
                mkdir -p "$target_dir"
                
                # Check required files - use dynamic filenames based on policy directory name
                # Find the policy file that matches the directory name (case-insensitive)
                policy_file=""
                policy_dir_name_lower=$(echo "$policy_dir_name" | tr '[:upper:]' '[:lower:]')

                for file in "$policy_dir"/*.policy.hcl; do
                    if [ -f "$file" ]; then
                        filename=$(basename "$file" .policy.hcl)
                        filename_lower=$(echo "$filename" | tr '[:upper:]' '[:lower:]')
                        if [ "$filename_lower" = "$policy_dir_name_lower" ]; then
                            policy_file="$file"
                            break
                        fi
                    fi
                done

                # ENG-02: collect EVERY test file, not just the one matching the directory name.
                # ENG-07: the primary file is <policy_dir>.policytest.hcl; extras use -N.
                primary_policytest=""
                numbered_policytests=()
                naming_error=""

                for file in "$policy_dir"/*.policytest.hcl; do
                    [ -f "$file" ] || continue
                    filename=$(basename "$file" .policytest.hcl)
                    filename_lower=$(echo "$filename" | tr '[:upper:]' '[:lower:]')

                    if [ "$filename_lower" = "$policy_dir_name_lower" ]; then
                        primary_policytest="$file"
                    elif [[ "$filename_lower" =~ ^${policy_dir_name_lower}-([0-9]+)$ ]]; then
                        numbered_policytests+=("$file")
                    else
                        naming_error="$(basename "$file")"
                        break
                    fi
                done

                if [ -n "$naming_error" ]; then
                    FAILED_POLICIES+=("$sentinel_path (test file does not follow naming convention: $naming_error)")
                    policy_found=true
                    break
                fi

                if [ -z "$policy_file" ] || [ -z "$primary_policytest" ] || [ ! -f "$policy_dir/main.tf" ] || [ ! -f "$policy_dir/report.md" ]; then
                    FAILED_POLICIES+=("$sentinel_path (missing files)")
                    policy_found=true
                    break
                fi

                # ENG-03: a test file may only target this policy directory's own policy.
                # The external repo layout puts each policy in its own directory, so a
                # multi-target test would be deployed without all of its target policies.
                # Fail with a clear error rather than producing an incomplete test suite.
                expected_target_lower="${policy_dir_name_lower}.policy.hcl"
                target_error=""

                for file in "$primary_policytest" "${numbered_policytests[@]}"; do
                    [ -f "$file" ] || continue
                    file_targets=$(extract_policytest_targets "$file")
                    if [ -z "$file_targets" ]; then
                        target_error="$(basename "$file") has no policytest.targets block"
                        break
                    fi
                    while IFS= read -r one_target; do
                        [ -z "$one_target" ] && continue
                        one_target_lower=$(echo "$one_target" | tr '[:upper:]' '[:lower:]')
                        if [ "$one_target_lower" != "$expected_target_lower" ]; then
                            target_error="$(basename "$file") targets a policy outside this directory: $one_target"
                            break
                        fi
                    done <<< "$file_targets"
                    [ -n "$target_error" ] && break
                done

                if [ -n "$target_error" ]; then
                    FAILED_POLICIES+=("$sentinel_path (multi-target or untargeted test file: $target_error)")
                    policy_found=true
                    break
                fi

                echo "📦 Deploying: $policy_dir_name → tfpolicy/$sentinel_basename/"

                cp "$policy_file" "$target_dir/$sentinel_basename.policy.hcl"
                echo "  ✓ $sentinel_basename.policy.hcl"

                # Deploy the primary test file, then the numbered ones, preserving the -N suffix.
                # ENG-10: the policy file is renamed to $sentinel_basename.policy.hcl, so the
                # targets inside each copied test file must be rewritten to match.
                cp "$primary_policytest" "$target_dir/$sentinel_basename.policytest.hcl"
                rewrite_policytest_targets "$target_dir/$sentinel_basename.policytest.hcl" "$sentinel_basename"
                echo "  ✓ $sentinel_basename.policytest.hcl"

                deployed_test_names=("$sentinel_basename.policytest.hcl")
                for file in "${numbered_policytests[@]}"; do
                    [ -f "$file" ] || continue
                    test_index="$(basename "$file" .policytest.hcl)"
                    test_index="${test_index##*-}"
                    cp "$file" "$target_dir/$sentinel_basename-$test_index.policytest.hcl"
                    rewrite_policytest_targets "$target_dir/$sentinel_basename-$test_index.policytest.hcl" "$sentinel_basename"
                    echo "  ✓ $sentinel_basename-$test_index.policytest.hcl"
                    deployed_test_names+=("$sentinel_basename-$test_index.policytest.hcl")
                done

                # Remove numbered test files left over from a previous deployment of this
                # policy. Only files this tool names are considered, and only files that are
                # not part of the set just deployed (comparing against the deployed names —
                # not against a count — so a non-contiguous -N sequence is never self-deleted).
                for stale in "$target_dir/$sentinel_basename"-*.policytest.hcl; do
                    [ -f "$stale" ] || continue
                    stale_name="$(basename "$stale")"
                    stale_index="${stale_name%.policytest.hcl}"
                    stale_index="${stale_index##*-}"
                    case "$stale_index" in
                        ''|*[!0-9]*) continue ;;
                    esac
                    still_deployed=false
                    for kept in "${deployed_test_names[@]}"; do
                        if [ "$kept" = "$stale_name" ]; then
                            still_deployed=true
                            break
                        fi
                    done
                    if [ "$still_deployed" = false ]; then
                        rm -f "$stale"
                        echo "  ⊘ Removed obsolete $stale_name"
                    fi
                done

                # main.tf is an internal artifact: it is the validated resource schema that
                # Stage 2 uses to author the policy and Stage 4 uses to build fixtures. It is
                # not part of the policy the external repo consumes, so it is not deployed.
                # The same applies to Stage 4's pass_config.tf / fail_config.tf, which are
                # likewise never copied.

                cp "$policy_dir/report.md" "$target_dir/$sentinel_basename.report.md"
                echo "  ✓ $sentinel_basename.report.md"

                # ENG-08: the deployed report references ./gwt.json, so deploy it alongside.
                if [ -f "$policy_dir/gwt.json" ]; then
                    cp "$policy_dir/gwt.json" "$target_dir/gwt.json"
                    echo "  ✓ gwt.json"
                fi

                DEPLOYED_POLICIES+=("$sentinel_path")
                policy_found=true
                echo ""
                break
            done
        fi
    done < <(grep -A 1000 "^| Generated TF Policy Name" "$summary_file" | grep "^|")

    echo "=========================================="
    echo "✓ Deployment Complete!"
    echo "=========================================="
    echo ""
    echo "Summary:"
    echo "  Deployed: ${#DEPLOYED_POLICIES[@]} policies"
    echo "  Failed: ${#FAILED_POLICIES[@]} policies"
    echo "  Target: $EXTERNAL_REPO_DIR"
    echo ""

    if [ ${#DEPLOYED_POLICIES[@]} -gt 0 ]; then
        echo "Successfully Deployed Policies:"
        for policy in "${DEPLOYED_POLICIES[@]}"; do
            echo "  ✓ $policy"
        done
        echo ""
    fi

    if [ ${#FAILED_POLICIES[@]} -gt 0 ]; then
        echo "Failed Policies (NOT deployed):"
        for policy in "${FAILED_POLICIES[@]}"; do
            echo "  ✗ $policy"
        done
        echo ""
    fi

    echo "Next steps:"
    echo "  1. Review generated policies in: $EXTERNAL_REPO_DIR"
    echo "  2. Commit and push changes:"
    echo "     cd $EXTERNAL_REPO_DIR"
    echo "     git add tfpolicy/"
    echo "     git commit -m 'Add generated TF policies'"
    echo "     git push"
    echo ""
fi

# Made with Bob
